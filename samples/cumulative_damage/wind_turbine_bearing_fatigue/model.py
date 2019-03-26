# ______          _           _     _ _ _     _   _      
# | ___ \        | |         | |   (_) (_)   | | (_)     
# | |_/ / __ ___ | |__   __ _| |__  _| |_ ___| |_ _  ___ 
# |  __/ '__/ _ \| '_ \ / _` | '_ \| | | / __| __| |/ __|
# | |  | | | (_) | |_) | (_| | |_) | | | \__ \ |_| | (__ 
# \_|  |_|  \___/|_.__/ \__,_|_.__/|_|_|_|___/\__|_|\___|
# ___  ___          _                 _                  
# |  \/  |         | |               (_)                 
# | .  . | ___  ___| |__   __ _ _ __  _  ___ ___         
# | |\/| |/ _ \/ __| '_ \ / _` | '_ \| |/ __/ __|        
# | |  | |  __/ (__| | | | (_| | | | | | (__\__ \        
# \_|  |_/\___|\___|_| |_|\__,_|_| |_|_|\___|___/        
#  _           _                     _                   
# | |         | |                   | |                  
# | |     __ _| |__   ___  _ __ __ _| |_ ___  _ __ _   _ 
# | |    / _` | '_ \ / _ \| '__/ _` | __/ _ \| '__| | | |
# | |___| (_| | |_) | (_) | | | (_| | || (_) | |  | |_| |
# \_____/\__,_|_.__/ \___/|_|  \__,_|\__\___/|_|   \__, |
#                                                   __/ |
#                                                  |___/ 
#														  
# MIT License
# 
# Copyright (c) 2019 Probabilistic Mechanics Laboratory
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ==============================================================================

import numpy as np
import tensorflow as tf

from tensorflow.keras.models import Model
from tensorflow.keras.layers import Input, Multiply, Lambda, Concatenate, Reshape
from tensorflow.python.framework import tensor_shape

import sys
sys.path.append('../../../')

from pinn.layers import CumulativeDamageCell
from pinn.layers.physics import SNCurve
from pinn.layers.core import inputsSelection, tableInterpolation

# Model
def create_model(a, b, Pu, grid_array_aSKF, bounds_aSKF, table_shape_aSKF, grid_array_kappa, bounds_kappa, table_shape_kappa, grid_array_etac, bounds_etac, table_shape_etac, d0RNN, batch_input_shape, selectCycle, selectLoad, selectBTemp, myDtype, return_sequences = False, unroll = False):
    
    batch_adjusted_shape = (batch_input_shape[0], batch_input_shape[1], batch_input_shape[2]+1) #Adding state
    placeHolder = Input(shape=(batch_input_shape[0], batch_input_shape[2]+1,)) #Adding state
    
    filterCycleLayer = inputsSelection(batch_adjusted_shape, selectCycle)(placeHolder)
    
    filterLoadLayer = inputsSelection(batch_adjusted_shape, selectLoad)(placeHolder)
    
    filterBTempLayer = inputsSelection(batch_adjusted_shape, selectBTemp)(placeHolder)
    
    kappaXvalLayer = Concatenate(axis = -1)([filterBTempLayer,filterBTempLayer])
    
    kappaLayer = tableInterpolation(input_shape = kappaXvalLayer.shape)
    kappaLayer.build(input_shape = table_shape_kappa)
    kappaLayer.set_weights([grid_array_kappa, bounds_kappa])
    kappaLayer.trainable = False
    kappaLayer = kappaLayer(kappaXvalLayer)
    
    etacXvalLayer = Concatenate(axis = -1)([kappaLayer,kappaLayer])
    
    etacLayer = tableInterpolation(input_shape = etacXvalLayer.shape)
    etacLayer.build(input_shape = table_shape_etac)
    etacLayer.set_weights([grid_array_etac, bounds_etac])
    etacLayer.trainable = False
    etacLayer = etacLayer(etacXvalLayer)
    
    xvalLayer1 = Lambda(lambda x: Pu*x)(etacLayer)
    xvalLayer2 = Lambda(lambda x: 1/(10**x))(filterLoadLayer)
    xvalLayer = Multiply()([xvalLayer1, xvalLayer2])
    
    n = batch_input_shape[0]
    sn_input_shape = (n, batch_input_shape[2])
    
    SNLayer = SNCurve(input_shape = sn_input_shape, dtype = myDtype)
    SNLayer.build(input_shape = sn_input_shape)
    SNLayer.set_weights([np.asarray([a, b], dtype = SNLayer.dtype)])
    SNLayer.trainable = False
    SNLayer = SNLayer(filterLoadLayer)
    
    multiplyLayer1 = Multiply()([SNLayer, filterCycleLayer])

    xvalLayer = Concatenate(axis = -1)([xvalLayer,kappaLayer])
    
    aSKFLayer = tableInterpolation(input_shape = xvalLayer.shape)
    aSKFLayer.build(input_shape = table_shape_aSKF)
    aSKFLayer.set_weights([grid_array_aSKF, bounds_aSKF])
    aSKFLayer.trainable = False
    aSKFLayer = aSKFLayer(xvalLayer)
    aSKFLayer = Lambda(lambda x: 1/x)(aSKFLayer)
    
    multiplyLayer2 = Multiply()([multiplyLayer1, aSKFLayer])
        
    functionalModel = Model(inputs = [placeHolder], outputs = [multiplyLayer2])

    "-------------------------------------------------------------------------"
    CDMCellHybrid = CumulativeDamageCell(model = functionalModel,
                                       batch_input_shape = batch_input_shape,
                                       dtype = myDtype,
                                       initial_damage = d0RNN)
    
    CDMRNNhybrid = tf.keras.layers.RNN(cell = CDMCellHybrid,
                                       return_sequences = return_sequences,
                                       return_state = False,
                                       batch_input_shape = batch_input_shape,
                                       unroll = unroll)
    
    model = tf.keras.Sequential()
    model.add(CDMRNNhybrid)
    model.compile(loss='mse', optimizer=tf.keras.optimizers.RMSprop(1e-12), metrics=['mae'])
    return model