# Copyright 2017 Rice University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function
import argparse
import re
import tensorflow as tf
from tensorflow.python.client import device_lib
from itertools import chain
import numpy as np
import os
#import matplotlib.pyplot as plt

# Do not move these imports to the top, it will introduce a cyclic dependency
import bayou.models.low_level_evidences.evidence


# convert JSON to config
def read_config(js, chars_vocab=False):
    config = argparse.Namespace()

    for attr in CONFIG_GENERAL:
        config.__setattr__(attr, js[attr])

    config.evidence, config.surrounding_evidence = bayou.models.non_prob.evidence.Evidence.read_config(js['evidence'], chars_vocab)

    config.decoder = argparse.Namespace()
    for attr in CONFIG_DECODER:
        config.decoder.__setattr__(attr, js['decoder'][attr])
    if chars_vocab:
        for attr in CONFIG_INFER:
            config.decoder.__setattr__(attr, js['decoder'][attr])
    config.reverse_encoder = argparse.Namespace()
    # added two paragraph  of new code for reverse encoder
    for attr in CONFIG_REVERSE_ENCODER:
        config.reverse_encoder.__setattr__(attr, js['reverse_encoder'][attr])
    if chars_vocab:
        for attr in CONFIG_INFER:
            config.reverse_encoder.__setattr__(attr, js['reverse_encoder'][attr])
    return config