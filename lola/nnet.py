"""
:Authors: - Wilker Aziz
"""
import theano
import theano.tensor as T
import numpy as np
from numpy import array as nparray
from theano.tensor.var import TensorVariable
from theano.tensor.elemwise import Elemwise
from typing import List, Iterable


def make_random_matrix(rng, n_input, n_output, activation=T.tanh):
    """
    From http://deeplearning.net/tutorial/mlp.html

    W is uniformely sampled from sqrt(-6./(n_in+n_hidden)) and sqrt(6./(n_in+n_hidden)),
     the output of uniform if converted using asarray to dtype
     theano.config.floatX so that the code is runable on GPU
     Note : optimal initialization of weights is dependent on the
            activation function used (among other things).
            For example, results presented in [Xavier10] suggest that you
            should use 4 times larger initial weights for sigmoid
            compared to tanh
            We have no info for other function, so we use the same as
            tanh.
    """
    W = np.asarray(
        rng.uniform(
            low=-np.sqrt(6. / (n_input + n_output)),
            high=np.sqrt(6. / (n_input + n_output)),
            size=(n_input, n_output)
        ),
        dtype=theano.config.floatX
    )
    if activation and activation == theano.tensor.nnet.sigmoid:
        W *= 4
    return W


class Layer:

    def __init__(self, n_input: int, n_output: int, W: nparray, b: nparray, activation: Elemwise = T.tanh):
        """
        A layer of a neural network, computes s(Wx + b) where s is a nonlinearity and x is the input vector.

        :parameters:
            - rng: numpy random state
            - n_in: input dimensionality
            - n_out: output dimensionality
            - W: np.array, shape=(n_in, n_out)
                Optional weight matrix, if not given is initialised randomly.
            - b: np.array, shape=(n_out,)
                Optional bias vector, if not given is initialised randomly.
            - activation : theano.tensor.elemwise.Elemwise
                Activation function for layer output
        """
        assert W.shape == (n_input, n_output), \
            'W does not match the expected dimensionality (%d, %d) != %s' % (n_input, n_output, W.shape)
        assert b.shape == (n_output,), 'b does not match the expected dimensionality (%d,) != %s' % (n_output, b.shape)

        self.n_input = n_input
        self.n_output = n_output
        # All parameters should be shared variables.
        # They're used in this class to compute the layer output,
        # but are updated elsewhere when optimizing the network parameters.
        # Note that we are explicitly requiring that W_init has the theano.config.floatX dtype
        self.W = theano.shared(value=W.astype(theano.config.floatX),
                               # The name parameter is solely for printing purporses
                               name='W',
                               # Setting borrow=True allows Theano to use user memory for this object.
                               # It can make code slightly faster by avoiding a deep copy on construction.
                               # For more details, see
                               # http://deeplearning.net/software/theano/tutorial/aliasing.html
                               borrow=True)

        # We can force our bias vector b to be a column vector using numpy's reshape method.
        # When b is a column vector, we can pass a matrix-shaped input to the layer
        # and get a matrix-shaped output, thanks to broadcasting (described below)
        self.b = theano.shared(value=b.astype(theano.config.floatX),
                               name='b',
                               borrow=True)

        self.activation = activation

        # We'll compute the gradient of the cost of the network with respect to the parameters in this list.
        self.params = [self.W, self.b]

    def output(self, x: TensorVariable) -> TensorVariable:
        """
        Compute this layer's output given an input

        :parameters:
            - x : theano.tensor.var.TensorVariable
                Theano symbolic variable for layer input

        :returns:
            Mixed, biased, and activated x
        """
        # Compute linear mix
        lin_output = T.dot(x, self.W) + self.b
        # Output is just linear mix if no activation function
        # Otherwise, apply the activation function
        return lin_output if self.activation is None else self.activation(lin_output)


class NNBuilder:

    def __init__(self, rng):
        self._rng = rng
        self._layers = []  # type: List[Layer]

    def add_layer(self, n_input: int, n_output: int,
                  W: nparray = None, b: nparray = None,
                  activation: Elemwise = T.tanh):
        """

        :parameters:
            - n_input: input dimensionality
            - n_output: output dimensionality
            - W: np.array, shape=(n_input, n_output)
                Optional weight matrix (default: random initialisation)
            - b: np.array, shape=(n_input, n_output)
                Optional bias vector (default: 0s)
            - activation:
                Elementwise activation function (default: tanh)
        :returns:
            self
        """
        if self._layers:
            if self._layers[-1].n_output != n_input:
                i = len(self._layers)
                raise ValueError('Cannot wire hidden layers %d (n_output=%d) and %d (n_input=%d)' %
                                 (i, self._layers[-1].n_output, i + 1, n_input))
        if W is None:
            W = make_random_matrix(self._rng, n_input, n_output, activation)
        if b is None:
            b = np.zeros((n_output,), dtype=theano.config.floatX)
        self._layers.append(Layer(n_input, n_output, W, b, activation))
        return self

    def iterlayers(self) -> Iterable[Layer]:
        return iter(self._layers)

    def n_input(self):
        """Input dimensionality"""
        if self._layers:
            return self._layers[0].n_input
        raise ValueError('I have no layers')

    def n_output(self):
        """Current output dimensionality"""
        if self._layers:
            return self._layers[-1].n_output
        raise ValueError('I have no layers')

    def reset(self):
        self._layers = []


class MLP:

    def __init__(self, builder: NNBuilder, n_classes: int):
        """
        Multi-layer perceptron class, computes the composition of a sequence of Layers.
        It effectively trains builder.n_input classifiers, each of which defined over n_classes.

        :parameters:
            - builder : NNBuilder
                A builder object that contains the configured layers.
                On top of these layers, MLP will add a softmax layer over n_classes (see below).
            - n_classes : number of output classes
        """

        # final layers is a softmax over a number of classes
        builder.add_layer(builder.n_output(), n_classes, activation=T.nnet.softmax)

        # Initialize lists of layers
        self.layers = []  # type: List[Layer]
        for layer in builder.iterlayers():
            self.layers.append(layer)
        builder.reset()

        # Combine parameters from all layers
        self.params = []
        for layer in self.layers:
            self.params += layer.params

        self.n_input = self.layers[0].n_input
        self.n_output = self.layers[-1].n_output

    def output(self, x: TensorVariable) -> TensorVariable:
        """
        Compute the MLP's output given an input

        :parameters:
            - x : theano.tensor.var.TensorVariable
                One row per classifier.

        :returns:
            - output : theano.tensor.var.TensorVariable
                One categorical distribution over n_classes per classifier.
        """
        for layer in self.layers:  # recursively transforms x
            x = layer.output(x)
        return x

    def expected_logprob(self, x: TensorVariable,
                         mu: TensorVariable) -> TensorVariable:
        """

        :parameters:
            - x : theano.tensor.var.TensorVariable
                This should contain one row per classifier.
            - mu : theano.tensor.var.TensorVariable
                For each row in x, this has expected levels over n_classes

        :returns:
            - sum of expected log prob : theano.tensor.var.TensorVariable
        """

        return T.sum(T.mul(mu, T.log(self.output(x))))


class LR:

    def __init__(self, builder: NNBuilder, n_contexts: int, n_decisions: int):
        """
        Logistic regression class.
        Let c be a context and d be a decision, let f(c, d) \in R^n be a feature representation.
        This class computes:
            p(d|c) \propto exp(w.dot(f(c,d)))
        where normalisation happens wrt the given context over a number of decisions (n_decisions).

        :parameters:
            - builder : NNBuilder
                A builder object that contains the configured layers.
                On top of these layers, LR will add a linear layer.
            - n_contexts : number of CPDs
            - n_decisions : size of the support of these CPDs
        """

        self.n_contexts = n_contexts
        self.n_decisions = n_decisions

        # this is the scoring layer
        builder.add_layer(builder.n_output(), 1, activation=None)

        # Initialize lists of layers
        self.layers = []  # type: List[Layer]
        for layer in builder.iterlayers():
            self.layers.append(layer)
        builder.reset()

        # Combine parameters from all layers
        self.params = []
        for layer in self.layers:
            self.params += layer.params

        self.n_input = self.layers[0].n_input
        self.n_output = self.layers[-1].n_output

    def output(self, x: TensorVariable) -> TensorVariable:
        """
        Compute the LR's output.

        :parameters:
            - x : theano.tensor.var.TensorVariable
                This should be a matrix with (n_contexts * n_decisions) rows.

        :returns:
            - output : theano.tensor.var.TensorVariable
                For each pair (c, d), the probability p(d|c) properly normalised.
        """

        for layer in self.layers:  # recursively transforms x
            x = layer.output(x)
        original_shape = x.shape
        # reshape potentials into a CPD style matrix
        # compute a softmax per row
        # reshape it back into a long matrix
        return T.nnet.softmax(x.reshape((self.n_contexts, self.n_decisions))).reshape(original_shape)

    def expected_logprob(self, x: TensorVariable,
                         mu: TensorVariable) -> TensorVariable:
        """

        :parameters:
            - x : theano.tensor.var.TensorVariable
                This should be a matrix with (n_contexts * n_decisions) rows.
            - mu : theano.tensor.var.TensorVariable
                This should associated to each row in x an expected output level.

        :returns:
            - sum of expected log prob : theano.tensor.var.TensorVariable
        """
        return T.sum(T.mul(mu, T.log(self.output(x))))


def gradient_updates_momentum(cost, params, learning_rate, momentum):
    """
    Compute updates for gradient descent with momentum

    :parameters:
        - cost : theano.tensor.var.TensorVariable
            Theano cost function to minimize
        - params : list of theano.tensor.var.TensorVariable
            Parameters to compute gradient against
        - learning_rate : float
            Gradient descent learning rate
        - momentum : float
            Momentum parameter, should be at least 0 (standard gradient descent) and less than 1

    :returns:
        updates : list
            List of updates, one for each parameter
    """
    # Make sure momentum is a sane value
    assert momentum < 1 and momentum >= 0
    # List of update steps for each parameter
    updates = []
    # Just gradient descent on cost
    for param in params:
        # For each parameter, we'll create a previous_step shared variable.
        # This variable will keep track of the parameter's update step across iterations.
        # We initialize it to 0
        previous_step = theano.shared(param.get_value() * 0., broadcastable=param.broadcastable)
        # Each parameter is updated by taking a step in the direction of the gradient.
        # However, we also "mix in" the previous step according to the given momentum value.
        # Note that we don't need to derive backpropagation to compute updates - just use T.grad!
        step = momentum * previous_step - learning_rate * T.grad(cost, param)
        # Add an update to store the previous step value
        updates.append((previous_step, step))
        # Add an update to apply the gradient descent step to the parameter itself
        updates.append((param, param + step))
    return updates