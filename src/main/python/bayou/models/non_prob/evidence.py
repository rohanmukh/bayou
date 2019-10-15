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

import tensorflow as tf
import numpy as np
import os
import re
import json
import nltk
from itertools import chain
from collections import Counter
import gensim
from bayou.models.low_level_evidences.utils import CONFIG_ENCODER, CONFIG_INFER
from bayou.models.low_level_evidences.seqEncoder import seqEncoder
from bayou.models.low_level_evidences.biRNN import biRNN
from bayou.models.non_prob.surrounding_evidences import *

from nltk.stem.wordnet import WordNetLemmatizer
lemmatizer = WordNetLemmatizer()
import wordninja

class Evidence(object):


    def init_config(self, evidence, chars_vocab):
        for attr in CONFIG_ENCODER + (CONFIG_INFER if chars_vocab else []):
            self.__setattr__(attr, evidence[attr])

    def dump_config(self):
        js = {attr: self.__getattribute__(attr) for attr in CONFIG_ENCODER + CONFIG_INFER}
        return js

    @staticmethod
    def read_config(js, chars_vocab):
        evidences = []
        surrounding_evs = []
        for evidence in js:
            name = evidence['name']
            if name == 'apicalls':
                e = APICalls()
            elif name == 'types':
                e = Types()
            elif name == 'keywords':
                e = Keywords()
            elif name == 'callsequences':
                e = CallSequences()
            elif name == 'returntype':
                e = ReturnType()
            elif name == 'formalparam':
                e = FormalParam()
            elif name == 'javadoc':
                e = JavaDoc()
            elif name == 'classtype':
                e = ClassTypes()
            elif name == 'method_name':
                e = MethodName()
            elif name == 'class_name':
                e = ClassName()
            elif name == 'surrounding_evidence':
                e = SurroundingEvidence()
                internal_evidences = e.read_config(evidence["evidence"], chars_vocab) # evidence is the json
            else:
                raise TypeError('Invalid evidence name: {}'.format(name))
            e.name = name
            e.init_config(evidence, chars_vocab)
            evidences.append(e)
            if name == 'surrounding_evidence':
                surrounding_evs.extend(internal_evidences)

        return evidences, surrounding_evs

    def word2num(self, listOfWords, infer):
        output = []
        for word in listOfWords:
            if word not in self.vocab:
                if not infer:
                    self.vocab[word] = self.vocab_size
                    self.vocab_size += 1
                    output.append(self.vocab[word])
            else:
                output.append(self.vocab[word])
                # with open("/home/ubuntu/evidences_used.txt", "a") as f:
                #      f.write('Evidence Type :: ' + self.name + " , " + "Evidence Value :: " + word + "\n")

        return output

    def read_data_point(self, program, infer):
        raise NotImplementedError('read_data() has not been implemented')

    def set_chars_vocab(self, data):
        raise NotImplementedError('set_chars_vocab() has not been implemented')

    def wrangle(self, data):
        raise NotImplementedError('wrangle() has not been implemented')

    def placeholder(self, config):
        # type: (object) -> object
        raise NotImplementedError('placeholder() has not been implemented')

    def exists(self, inputs, config, infer):
        raise NotImplementedError('exists() has not been implemented')

    def init_sigma(self, config):
        raise NotImplementedError('init_sigma() has not been implemented')

    def encode(self, inputs, config):
        raise NotImplementedError('encode() has not been implemented')

    def split_words_underscore_plus_camel(self, s):

        # remove unicode
        s = s.encode('ascii', 'ignore').decode('unicode_escape')
        #remove numbers
        s = re.sub(r'\d+', '', s)
        #substitute all non alphabets by # to be splitted later
        s = re.sub("[^a-zA-Z]+", "#", s)
        #camel case split
        s = re.sub('(.)([A-Z][a-z]+)', r'\1#\2', s)  # UC followed by LC
        s = re.sub('([a-z0-9])([A-Z])', r'\1#\2', s)  # LC followed by UC
        vars = s.split('#')

        final_vars = []
        for var in vars:
            var = var.lower()
            w = lemmatizer.lemmatize(var, 'v')
            w = lemmatizer.lemmatize(w, 'n')
            len_w = len(w)
            if len_w > 1 and len_w < 10 :
                final_vars.append(w)
        return final_vars

class Sets(Evidence):


    def wrangle(self, data):
        wrangled = np.zeros((len(data), self.max_nums), dtype=np.int32)
        for i, calls in enumerate(data):
            for j, c in enumerate(calls):
                if j < self.max_nums:
                    wrangled[i, j] = c
        return wrangled

    def placeholder(self, config):
        # type: (object) -> object
        return tf.placeholder(tf.int32, [config.batch_size, self.max_nums])

    def exists(self, inputs, config, infer):
        i = tf.expand_dims(tf.reduce_sum(inputs, axis=1),axis=1)
        # Drop a few types of evidences during training
        if not infer:
            i_shaped_zeros = tf.zeros_like(i)
            rand = tf.random_uniform( (config.batch_size,1) )
            i = tf.where(tf.less(rand, self.ev_drop_prob) , i, i_shaped_zeros)

        i = tf.reduce_sum(i, axis=1)

        return tf.not_equal(i, 0)

    def init_sigma(self, config):
        with tf.variable_scope(self.name):
            self.emb = tf.get_variable('emb', [self.vocab_size, self.units])
        # with tf.variable_scope('global_sigma', reuse=tf.AUTO_REUSE):
            self.sigma = tf.get_variable('sigma', [])

    def encode(self, inputs, config, infer):
        with tf.variable_scope(self.name):

            # Drop some inputs
            if not infer:
                inp_shaped_zeros = tf.zeros_like(inputs)
                rand = tf.random_uniform( (config.batch_size, self.max_nums) )
                inputs = tf.where(tf.less(rand, self.ev_call_drop_prob) , inputs, inp_shaped_zeros)

            inputs = tf.reshape(inputs, [-1])

            emb_inp = tf.nn.embedding_lookup(self.emb, inputs)
            encoding = tf.layers.dense(emb_inp, self.units, activation=tf.nn.tanh)
            for i in range(self.num_layers - 1):
                encoding = tf.layers.dense(encoding, self.units, activation=tf.nn.tanh)

            w = tf.get_variable('w', [self.units, config.latent_size])
            b = tf.get_variable('b', [config.latent_size])
            latent_encoding = tf.nn.xw_plus_b(encoding, w, b)

            zeros = tf.zeros([config.batch_size * self.max_nums, config.latent_size])
            condition = tf.not_equal(inputs, 0)

            latent_encoding = tf.where(condition, latent_encoding, zeros)
            latent_encoding = tf.reshape(latent_encoding , [config.batch_size, self.max_nums, config.latent_size])
            count = tf.math.count_nonzero(tf.reduce_sum(latent_encoding, axis=2), axis=1)
            latent_encoding = tf.reduce_sum(latent_encoding, axis=1)/count
            return latent_encoding



# handle sequences as i/p
class Sequences(Evidence):


    def placeholder(self, config):
        # type: (object) -> object
        return tf.placeholder(tf.int32, [config.batch_size, self.max_depth])

    def wrangle(self, data):
        wrangled = np.zeros((len(data), self.max_depth), dtype=np.int32)
        for i, seqs in enumerate(data):
            seq = seqs[0]# NOT A BUG every sequence is read as List of List
            for pos,c in enumerate(seq):
                if pos < self.max_depth and c != 0:
                    wrangled[i, self.max_depth - 1 - pos] = c
        return wrangled

    def exists(self, inputs, config, infer):
        i = tf.expand_dims(tf.reduce_sum(inputs, axis=1),axis=1)
        # Drop a few types of evidences during training
        if not infer:
            i_shaped_zeros = tf.zeros_like(i)
            rand = tf.random_uniform( (config.batch_size,1) )
            i = tf.where(tf.less(rand, self.ev_drop_prob) , i, i_shaped_zeros)
        i = tf.reduce_sum(i, axis=1)

        return tf.not_equal(i, 0)


    def init_sigma(self, config):
        with tf.variable_scope(self.name):
            self.emb = tf.get_variable('emb', [self.vocab_size, self.units])
        # with tf.variable_scope('global_sigma', reuse=tf.AUTO_REUSE):
            self.sigma = tf.get_variable('sigma', [])

    def encode(self, inputs, config, infer):
        with tf.variable_scope(self.name):
            # Drop some inputs
            if not infer:
                inp_shaped_zeros = tf.zeros_like(inputs)
                rand = tf.random_uniform( (config.batch_size, self.max_depth) )
                inputs = tf.where(tf.less(rand, self.ev_call_drop_prob) , inputs, inp_shaped_zeros)

            LSTM_Encoder = seqEncoder(self.num_layers, self.units, inputs, config.batch_size, self.emb, config.latent_size)
            encoding = LSTM_Encoder.output

            w = tf.get_variable('w', [self.units, config.latent_size ])
            b = tf.get_variable('b', [config.latent_size])
            latent_encoding = tf.nn.xw_plus_b(encoding, w, b)

            zeros = tf.zeros([config.batch_size , config.latent_size])
            latent_encoding = tf.where( tf.not_equal(tf.reduce_sum(inputs, axis=1),0),latent_encoding, zeros)

            return latent_encoding



class APICalls(Sets):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1


    def read_data_point(self, program, infer):
        apicalls = program['apicalls'] if 'apicalls' in program else []
        return self.word2num(list(set(apicalls)) , infer)


    @staticmethod
    def from_call(callnode):
        call = callnode['_call']
        call = re.sub('^\$.*\$', '', call)  # get rid of predicates
        name = call.split('(')[0].split('.')[-1]
        name = name.split('<')[0]  # remove generics from call name
        return [name] if name[0].islower() else []  # Java convention

class Types(Sets):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        types = program['types'] if 'types' in program else []
        return self.word2num(list(set(types)), infer)

    @staticmethod
    def get_types_re(s):
        patt = re.compile('java[x]?\.(\w*)\.(\w*)(\.([A-Z]\w*))*')
        types = [match.group(4) if match.group(4) is not None else match.group(2)
                 for match in re.finditer(patt, s)]
        primitives = {
            'byte': 'Byte',
            'short': 'Short',
            'int': 'Integer',
            'long': 'Long',
            'float': 'Float',
            'double': 'Double',
            'boolean': 'Boolean',
            'char': 'Character'
        }

        for p in primitives:
            if s == p or re.search('\W{}'.format(p), s):
                types.append(primitives[p])
        return list(set(types))

    @staticmethod
    def from_call(callnode):
        call = callnode['_call']
        types = Types.get_types_re(call)

        if '_throws' in callnode:
            for throw in callnode['_throws']:
                types += Types.get_types_re(throw)

        if '_returns' in callnode:
            types += Types.get_types_re(callnode['_returns'])

        return list(set(types))



class Variables(Sets):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        variables = program['my_variables'] if 'my_variables' in program else []
        return self.word2num(list(set(variables)), infer)



class Keywords(Sets):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    STOP_WORDS = {  # CoreNLP English stop words
        "'ll", "'s", "'m", "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
        "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between",
        "both", "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
        "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
        "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
        "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll",
        "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me",
        "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only",
        "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
        "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", "that's",
        "the", "their", "theirs", "them", "themselves", "then", "there", "there's", "these", "they",
        "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too", "under",
        "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't",
        "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom",
        "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
        "your", "yours", "yourself", "yourselves", "return", "arent", "cant", "couldnt", "didnt", "doesnt",
        "dont", "hadnt", "hasnt", "havent", "hes", "heres", "hows", "im", "isnt", "its", "lets", "mustnt",
        "shant", "shes", "shouldnt", "thats", "theres", "theyll", "theyre", "theyve", "wasnt", "were",
        "werent", "whats", "whens", "wheres", "whos", "whys", "wont", "wouldnt", "youd", "youll", "youre",
        "youve"
    }

    def lemmatize(self, word):
        w = lemmatizer.lemmatize(word, 'v')
        return lemmatizer.lemmatize(w, 'n')


    def read_data_point(self, program, infer):
        keywords = [self.lemmatize(k) for k in program['keywords']] if 'keywords' in program else []
        return self.word2num(list(set(keywords)), infer)



    @staticmethod
    def split_camel(s):
        s = re.sub('(.)([A-Z][a-z]+)', r'\1#\2', s)  # UC followed by LC
        s = re.sub('([a-z0-9])([A-Z])', r'\1#\2', s)  # LC followed by UC
        return s.split('#')

    @staticmethod
    def from_call(callnode):
        call = callnode['_call']
        call = re.sub('^\$.*\$', '', call)  # get rid of predicates
        qualified = call.split('(')[0]
        qualified = re.sub('<.*>', '', qualified).split('.')  # remove generics for keywords

        # add qualified names (java, util, xml, etc.), API calls and types
        keywords = list(chain.from_iterable([Keywords.split_camel(s) for s in qualified])) + \
            list(chain.from_iterable([Keywords.split_camel(c) for c in APICalls.from_call(callnode)])) + \
            list(chain.from_iterable([Keywords.split_camel(t) for t in Types.from_call(callnode)]))

        # convert to lower case, omit stop words and take the set
        return list(set([k.lower() for k in keywords if k.lower() not in Keywords.STOP_WORDS]))


class ReturnType(Sets):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1


    def read_data_point(self, program, infer):
        returnType = [program['returnType'] if 'returnType' in program else '__Constructor__']
        return self.word2num(returnType , infer)

class ClassTypes(Sets):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        classType = program['classTypes'] if 'classTypes' in program else []
        return self.word2num(classType, infer)




class MethodName(Sequences):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        methodName = program['method'] if 'method' in program else ''
        methodName = methodName.split('@')[0]
        method_name_tokens = self.split_words_underscore_plus_camel(methodName)
        return [self.word2num(method_name_tokens, infer)]






class ClassName(Sequences):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        className = program['file'] if 'file' in program else ''
        className = className.split('/')[-1]
        className = className.split('.')[0]
        class_name_tokens = self.split_words_underscore_plus_camel(className)
        return [self.word2num(class_name_tokens, infer)]






# handle sequences as i/p
class CallSequences(Sequences):
    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        json_seq = program['sequences'] if 'sequences' in program else []
        return [self.word2num(json_seq, infer)]


    @staticmethod
    def from_call(callnode):
        call = callnode['calls']
        call = re.sub('^\$.*\$', '', call)  # get rid of predicates
        name = call.split('(')[0].split('.')[-1]
        name = name.split('<')[0]  # remove generics from call name
        return [name] if name[0].islower() else []  # Java convention



# handle sequences as i/p
class FormalParam(Sequences):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1

    def read_data_point(self, program, infer):
        json_sequence = program['formalParam'] if 'formalParam' in program else []
        if 'None' not in json_sequence:
            json_sequence.insert(0, 'Start')
            json_sequence.insert(0, 'None')
        return [self.word2num(json_sequence, infer)]


# handle sequences as i/p
class JavaDoc(Sequences):

    def __init__(self):
        self.vocab = dict()
        self.vocab['None'] = 0
        self.vocab_size = 1
        self.word2vecModel = gensim.models.KeyedVectors.load_word2vec_format('/home/ubuntu/GoogleNews-vectors-negative300.bin', binary=True)
        self.n_Dims=300



    def read_data_point(self, program, infer):

        string_sequence = program['javaDoc'] if ('javaDoc' in program and program['javaDoc'] is not None) else []
        if len(string_sequence) == 0:
             return [[]]

        javadoc_list = string_sequence.strip().split()
        # replace all non alphabetical char into underscore
        javadoc_list = [re.sub("[^a-zA-Z]", '_', w) for w in javadoc_list]

            # break the terms using underscores
        tmp_list = []
        for t in javadoc_list:
               s = re.split("_+", t)
               tmp_list.extend(s)

        result_list = []
        for x in tmp_list:
            x = x.lower()
                # x = spell(x)

            x = wordninja.split(x)
            for word in x:
                y = lemmatizer.lemmatize(word, 'v')
                y = lemmatizer.lemmatize(y, 'n')
                if len(y) > 1:
                    result_list.append(y)

        return [self.word2num(result_list , infer)]

    def init_sigma(self, config):
        with tf.variable_scope(self.name):
            #REPLACE BY WORD2VEC
            # self.emb = tf.get_variable('emb', [self.vocab_size, self.units])

            vecrep_words = np.zeros((self.vocab_size,self.n_Dims), dtype=np.float32)
            for key in self.vocab:
            	vocab_ind = self.vocab[key]
            	if key in self.word2vecModel:
            		vecrep_words[vocab_ind] = self.word2vecModel[key]

            self.emb = tf.Variable(vecrep_words, name='emb',trainable=True)
        # with tf.variable_scope('global_sigma', reuse=tf.AUTO_REUSE):
            #self.sigma = tf.Variable(0.10, name='sigma', trainable=True) #tf.get_variable('sigma', [])
            self.sigma = tf.get_variable('sigma', [])


    def encode(self, inputs, config, infer):
        with tf.variable_scope(self.name):
            # Drop some inputs
            if not infer:
                inp_shaped_zeros = tf.zeros_like(inputs)
                rand = tf.random_uniform( (config.batch_size, self.max_depth) )
                inputs = tf.where(tf.less(rand, self.ev_call_drop_prob) , inputs, inp_shaped_zeros)

            BiGRU_Encoder = biRNN(self.num_layers, self.units, inputs, config.batch_size, self.emb, config.latent_size)
            encoding = BiGRU_Encoder.output

            w = tf.get_variable('w', [self.units, config.latent_size ])
            b = tf.get_variable('b', [config.latent_size])
            latent_encoding = tf.nn.xw_plus_b(encoding, w, b)

            zeros = tf.zeros([config.batch_size , config.latent_size])
            latent_encoding = tf.where( tf.not_equal(tf.reduce_sum(inputs, axis=1),0),latent_encoding, zeros)

            return latent_encoding


class SurroundingEvidence(Evidence):

    def __init__(self):
        self.vocab = None
        self.vocab_size = 0

    def read_data_point(self, program, infer):
        list_of_programs = program['Surrounding_Evidences'] if 'Surrounding_Evidences' in program else []
        # print(list_of_programs)
        data = [ev.read_data_point(list_of_programs, infer) for ev in self.internal_evidences] #self.config.surrounding_evidence]
        return data


    def wrangle(self, data):
        wrangled = [ev.wrangle(ev_data) for ev, ev_data in zip(self.internal_evidences , data )]

        return wrangled

    def placeholder(self, config):
        # type: (object) -> object
        return [ev.placeholder(config) for ev in config.surrounding_evidence]


    def exists(self, inputs, config, infer):

        temp = [ev.exists(input, config, infer) for input, ev in zip(inputs, config.surrounding_evidence)]
        i = tf.reduce_sum(tf.stack(temp, 0),0)
        i = tf.expand_dims(i,1)
        if not infer:
            i_shaped_zeros = tf.zeros_like(i)
            rand = tf.random_uniform( (config.batch_size, 1) )
            i = tf.where(tf.less(rand, self.ev_drop_prob) , i, i_shaped_zeros)

        i = tf.reduce_sum(i, axis=1)
        return tf.not_equal(i, 0)

    def init_sigma(self, config):
        with tf.variable_scope(self.name):
            # self.emb = tf.get_variable('emb', [self.vocab_size, self.units])
        # with tf.variable_scope('global_sigma', reuse=tf.AUTO_REUSE):
            self.sigma = tf.get_variable('sigma', [])
            [ev.init_sigma(config) for ev in config.surrounding_evidence]

    def dump_config(self):
        js = {attr: self.__getattribute__(attr) for attr in CONFIG_ENCODER + CONFIG_INFER}
        js['evidence'] = [ev.dump_config() for ev in self.internal_evidences]
        return js


    # @staticmethod
    def read_config(self, js, chars_vocab):
        evidences = []
        for evidence in js:
            name = evidence['name']
            if name == 'surr_sequences':
                e = surr_sequences()
            elif name == 'surr_methodName':
                e = surr_methodName()
            elif name == 'surr_header_vars':
                e = surr_header_vars()
            elif name == 'surr_returnType':
                e = surr_returnType()
            elif name == 'surr_formalParam':
                e = surr_formalParam()
            else:
                raise TypeError('Invalid evidence name: {}'.format(name))
            e.name = name
            e.init_config(evidence, chars_vocab)
            evidences.append(e)
        self.internal_evidences = evidences

        return evidences



    def encode(self, inputs, config, infer):
        with tf.variable_scope(self.name):
            encodings = [ev.encode(i, config, infer) for ev, i in zip(config.surrounding_evidence, inputs)]
            # list of number_of_ev :: batch_size * number_of_methods * latent_size
            encodings = tf.stack(encodings, axis=3)
            # batch_size * number_of_methods * latent_size * list_of_number_of_ev
            encodings = tf.reshape(encodings, [config.batch_size, self.max_nums, -1])
            # batch_size * number_of_methods * (latent_size * list_of_number_of_ev)

            #Now run neural neural_network
            #encodings_flat = tf.layers.dense( encodings , config.latent_size, activation=tf.nn.tanh)
            #encodings_flat = tf.layers.dense(encodings_flat, config.latent_size, activation=tf.nn.tanh)
            #encodings_flat = tf.layers.dense(encodings_flat, config.latent_size)
            #done

            encodings_flat = tf.layers.dense(encodings, config.latent_size)

            #zero check in method level
            zeros = tf.zeros_like(encodings_flat)
            cond = tf.not_equal(tf.reduce_sum(encodings, axis=2), 0)
            cond = tf.tile(tf.expand_dims(cond, axis=2),[1,1,config.latent_size])

            encodings_flat = tf.where( cond, encodings_flat , zeros)

            count = tf.nn.count_nonzero( tf.reduce_sum(encodings_flat, axis=2), axis=1 )

            #batch_size * number_of_methods * latent_size
            encodings_flat = tf.reduce_sum(encodings_flat, axis=1)/count[:,None]
        return encodings_flat