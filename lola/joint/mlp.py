"""
:Authors: - Wilker Aziz
"""
import logging
import theano
import theano.tensor as T
import numpy as np
from numpy import array as nparray
from lola.corpus import Corpus
from lola.nnet import MLP
from lola.nnet import NNBuilder
from lola.nnet import gradient_updates_momentum
from lola.joint.cat import SourceDistribution


class MLPLexical(SourceDistribution):
    """
    This MLP component functions as a Categorical distribution.
    The input is an English word and the output is a distribution over the French vocabulary.

    """

    def __init__(self, e_corpus: Corpus,
                 f_corpus: Corpus,
                 name: str = "lexmlp",
                 rng=np.random.RandomState(1234),
                 hidden=[100],
                 learning_rate=0.1,
                 max_iterations=100,
                 patience=10,
                 patience_increase=2,
                 improvement_threshold=0.995):
        """

        :param e_corpus: data we condition on
        :param f_corpus: data we generate
        :param name: name of the component
        :param rng: numpy random state
        :param hidden: dimensionality of hidden layers
        :param learning_rate: initial learning rate
        :param max_iterations: maximum number of updates
        :param patience: minimum number of updates
        :param patience_increase:
        :param improvement_threshold:
        """

        self._corpus_size = e_corpus.n_sentences()
        self._learning_rate = learning_rate
        self._max_iterations = max_iterations
        self._patience = patience
        self._patience_increase = patience_increase
        self._improvement_threshold = improvement_threshold

        # The event space determines the input and output dimensionality
        self.n_input, self.n_output = e_corpus.vocab_size(), f_corpus.vocab_size()
        # Input for the classifiers
        self._X = np.identity(self.n_input, dtype=theano.config.floatX)

        # Create MLP
        builder = NNBuilder(rng)
        # ... the embedding layer
        builder.add_layer(self.n_input, hidden[0])
        # ... additional hidden layers
        for di, do in zip(hidden, hidden[1:]):
            builder.add_layer(di, do)
        # The MLP adds a softmax layer over n_classes
        self._mlp = MLP(builder, n_classes=f_corpus.vocab_size())  # type: MLP

        # Create Theano variables for the MLP input
        mlp_input = T.matrix('mlp_input')
        # ... and the expected output
        mlp_expected = T.matrix('mlp_expected')
        learning_rate = T.scalar('learning_rate')

        # Learning rate and momentum hyperparameter values
        # Again, for non-toy problems these values can make a big difference
        # as to whether the network (quickly) converges on a good local minimum.
        #learning_rate = 0.01
        momentum = 0

        # Create a theano function for computing the MLP's output given some input
        self._mlp_output = theano.function([mlp_input], self._mlp.output(mlp_input))

        # Create a function for computing the cost of the network given an input
        cost = - self._mlp.expected_logprob(mlp_input, mlp_expected)

        # Create a theano function for training the network
        self._train = theano.function([mlp_input, mlp_expected, learning_rate],
                                      # cost function
                                      cost,
                                      updates=gradient_updates_momentum(cost,
                                                                        self._mlp.params,
                                                                        learning_rate,
                                                                        momentum))

        # table to store the CPDs (output of MLP)
        self._cpds = self._mlp_output(self._X)
        # table to gather expected counts
        self._counts = np.zeros((self.n_input, self.n_output), dtype=theano.config.floatX)
        self._i = 0

    def generate(self, fj: tuple, aj: tuple, e_snt: nparray, z: int, l: int, m: int):
        f = fj[1]
        i = aj[1]
        e = e_snt[i]
        return self._cpds[e, f]

    def observe(self, fj: tuple, aj: tuple, e_snt: nparray, z: int, l: int, m: int, posterior: float):
        f = fj[1]
        i = aj[1]
        e = e_snt[i]
        self._counts[e, f] += posterior

    def update(self):
        """
        A number of steps in the direction of the steepest decent,
         sufficient statistics are set to zero.
        """

        # First we need to scale the sufficient statistics by batch size
        self._counts /= self._corpus_size

        # We'll only train the network with 20 iterations.
        # A more common technique is to use a hold-out validation set.
        # When the validation error starts to increase, the network is overfitting,
        # so we stop training the net.  This is called "early stopping", which we won't do here.
        done_looping = False
        best_cost = np.inf
        best_iter = 0
        learning_rate = self._learning_rate
        patience = self._patience

        # TODO: implement adagrad
        for iteration in range(self._max_iterations):

            # Train the network using the entire training set.
            current_cost = self._train(self._X, self._counts, learning_rate)
            logging.debug('[%d] MLP cost=%s', iteration, current_cost)

            # Give it a chance to update cost and patience
            if current_cost < best_cost:
                if current_cost < best_cost * self._improvement_threshold:
                    if iteration >= patience - self._patience_increase:
                        patience += self._patience_increase
                best_cost = current_cost
                best_iter = iteration

            # Check patience
            if iteration > self._patience:
                logging.debug('Ran out of patience in iteration %d', iteration)
                break

        # Finally, we update the CPDs and reset the sufficient statistics to zero
        self._cpds = self._mlp_output(self._X)
        self._counts = np.zeros((self.n_input, self.n_output), dtype=theano.config.floatX)

