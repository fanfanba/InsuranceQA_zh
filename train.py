#!/usr/bin/env python
# -*- encoding:utf-8 -*-

"""
   Training part of the Deep QA model
   
"""

from __future__ import print_function
from __future__ import division

__copyright__ = "Copyright (c) 2017 Xuming Lin. All Rights Reserved"
__author__    = "Xuming Lin, Hai Liang Wang<hailiang.hl.wang@gmail.com>"
__date__      = "2017-08-21:23:42:17"

import os
curdir = os.path.dirname(os.path.abspath(__file__))

from qacnn import QACNN
import tensorflow as tf
import datetime
import operator
import data

flags, FLAGS = tf.app.flags, tf.app.flags.FLAGS

flags.DEFINE_integer('sequence_length', 200, 'sequence length')  # noqa: skipped autopep8 checking
flags.DEFINE_integer('num_epochs', 10000, 'epochs')  # noqa: skipped autopep8 checking
flags.DEFINE_integer('batch_size', 100, 'min batch size')  # noqa: skipped autopep8 checking
flags.DEFINE_integer('embedding_size', 100, 'embedding size')  # noqa: skipped autopep8 checking
flags.DEFINE_integer('hidden_size', 80, 'hidden size')  # noqa: skipped autopep8 checking
flags.DEFINE_integer('num_filters', 512, 'number of filters')  # noqa: skipped autopep8 checking
flags.DEFINE_float('l2_reg_lambda', 0., 'L2 regularization factor')  # noqa: skipped autopep8 checking
flags.DEFINE_float('keep_prob', 1.0, 'Dropout keep rate')  # noqa: skipped autopep8 checking
flags.DEFINE_float('lr', 0.01, 'learning rate')  # noqa: skipped autopep8 checking
flags.DEFINE_float('margin', 0.05, 'margin for computing loss')  # noqa: skipped autopep8 checking

# Config函数
class Config(object):
    def __init__(self, vocab_size):
        # 输入序列(句子)长度
        self.sequence_length = FLAGS.sequence_length
        # 循环数
        self.num_epochs = FLAGS.num_epochs
        # batch大小
        self.batch_size = FLAGS.batch_size
        # 词表大小
        self.vocab_size = vocab_size
        # 词向量大小
        self.embedding_size = FLAGS.embedding_size
        # 不同类型的filter,相当于1-gram,2-gram,3-gram和5-gram
        self.filter_sizes = [1, 2, 3, 5]
        # 隐层大小
        self.hidden_size = FLAGS.hidden_size
        # 每种filter的数量
        self.num_filters = FLAGS.num_filters
        # 论文里给的是0.0001
        self.l2_reg_lambda = FLAGS.l2_reg_lambda
        # dropout
        self.keep_prob = FLAGS.keep_prob
        # 学习率
        # 论文里给的是0.01
        self.lr = FLAGS.lr
        # margin
        # 论文里给的是0.009
        self.m = FLAGS.margin
        # 设定GPU的性质,允许将不能在GPU上处理的部分放到CPU
        # 设置log打印
        self.cf = tf.ConfigProto(allow_soft_placement=True, log_device_placement=False)
        '''
        GPU内存使用策略
        '''
        # 自动增长
        self.cf.gpu_options.allow_growth=True
        # 只占用20%的GPU内存
        # self.cf.gpu_options.per_process_gpu_memory_fraction = 0.2


print('Loading Data...')

# 词映射ID
vocab = data.vocab_data

# 配置文件
config = Config(len(vocab['word2id']))

def main(unused_argv):
    '''
    开始训练和测试
    '''
    with tf.device('/gpu:0'), tf.Session(config=config.cf) as sess:
        # 建立CNN网络
        cnn = QACNN(config, sess)
        # 保存Metrics数据
        tf_writer = tf.summary.FileWriter(logdir=os.path.join(curdir, 'sdist/'), graph=sess.graph)
        # Summaries for loss and accuracy during training
        summary_loss = tf.summary.scalar("train/loss", cnn.loss)
        summary_accu = tf.summary.scalar("train/accuracy", cnn.accu)
        summary_op = tf.summary.merge([summary_loss, summary_accu])

        # 训练函数
        def train_step(x_batch_1, x_batch_2, x_batch_3):
            feed_dict = {
                cnn.q: x_batch_1,
                cnn.aplus: x_batch_2,
                cnn.aminus: x_batch_3,
                cnn.keep_prob: config.keep_prob
            }
            _, step, loss, accuracy, summaries = sess.run(
                [cnn.train_op, cnn.global_step, cnn.loss, cnn.accu, summary_op],
                feed_dict)
            tf_writer.add_summary(summaries, step)
            time_str = datetime.datetime.now().isoformat()
            print("{}: step {}, loss {:g}, acc {:g}".format(time_str, step, loss, accuracy))
            return time_str, step, loss, accuracy

        # 测试函数
        def dev_step():
            results = dict()
            losses = []
            for qids, x_test_1, x_test_2, labels in data.load_valid(config.batch_size, config.sequence_length, config.sequence_length):
                if len(qids) != config.batch_size:
                    break
                feed_dict = {
                    cnn.q: x_test_1,
                    cnn.aplus: x_test_2,
                    cnn.aminus: x_test_2,
                    cnn.keep_prob: 1.0
                }
                batch_scores, step, loss = sess.run([cnn.q_ap_cosine, cnn.global_step, cnn.loss], feed_dict)
                losses.append(loss)
                for score, qid, label in zip(batch_scores, qids, labels):
                    results[qid] = [score, label]
            lev1 = .0
            lev0 = .0
            for k, v in results.items():
                # 使用0.5作为判定为正例的 Threshold
                # TODO for better evaluation, should use Roc Curve to find the best threshold
                if v[0] >= 0.5:
                    lev1 += 1
                else:
                    lev0 += 1
            # 评测回答的正确数和错误数
            accuracy = float(lev1)/(lev1+lev0)
            tf_writer.add_summary(tf.Summary(value=[
                tf.Summary.Value(tag="evaluate/loss", simple_value=tf.reduce_mean(losses).eval()),
                tf.Summary.Value(tag="evaluate/accuracy", simple_value=accuracy)]), step)

            print('回答正确数 ' + str(lev1))
            print('回答错误数 ' + str(lev0))
            print('准确率 ' + str(accuracy))

        # 每500步测试一下
        evaluate_every = 500
        # 开始训练和测试
        sess.run(tf.global_variables_initializer())
        for i in range(config.num_epochs):
            for (_, x_question, x_utterance, y) in data.load_train(config.batch_size, config.sequence_length, config.sequence_length):
                if len(_) == config.batch_size: # 在epoch的最后一个mini batch中，数据条数可能不等于 batch_size
                    _, global_step, _, _ = train_step(x_question, x_utterance, y)

                if (global_step+1) % evaluate_every == 0:
                    print("\n测试{}:".format((global_step+1)/evaluate_every))
                    dev_step()
                    print

if __name__ == '__main__':
    tf.app.run()