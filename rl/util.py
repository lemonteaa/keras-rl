import numpy as np

from keras.models import model_from_config, Sequential, Model, model_from_config
import keras.optimizers as optimizers
import keras.backend as K


def clone_model(model, custom_objects={}):
    # Requires Keras 1.0.7 since get_config has breaking changes.
    config = {
        'class_name': model.__class__.__name__,
        'config': model.get_config(),
    }
    clone = model_from_config(config, custom_objects=custom_objects)
    clone.set_weights(model.get_weights())
    return clone

def clone_model_customize(model, class_name=None, config=None, weights=None, custom_objects={}):
    # Requires Keras 1.0.7 since get_config has breaking changes.
    if class_name is None:
        class_name = model.__class__.__name__
    if config is None:
        config = model.get_config()
    if weights is None:
        weights = model.get_weights()
    config = {
        'class_name': class_name,
        'config': config,
    }
    clone = model_from_config(config, custom_objects=custom_objects)
    clone.set_weights(weights)
    return clone

def clone_optimizer(optimizer):
    if type(optimizer) is str:
        return optimizers.get(optimizer)
    # Requires Keras 1.0.7 since get_config has breaking changes.
    params = dict([(k, v) for k, v in optimizer.get_config().items()])
    config = {
        'class_name': optimizer.__class__.__name__,
        'config': params,
    }
    if hasattr(optimizers, 'optimizer_from_config'):
        # COMPATIBILITY: Keras < 2.0
        clone = optimizers.optimizer_from_config(config)
    else:
        clone = optimizers.deserialize(config)
    return clone


def get_soft_target_model_updates(target, source, tau):
    target_weights = target.trainable_weights + sum([l.non_trainable_weights for l in target.layers], [])
    source_weights = source.trainable_weights + sum([l.non_trainable_weights for l in source.layers], [])
    assert len(target_weights) == len(source_weights)

    # Create updates.
    updates = []
    for tw, sw in zip(target_weights, source_weights):
        updates.append((tw, tau * sw + (1. - tau) * tw))
    return updates


def get_object_config(o):
    if o is None:
        return None
        
    config = {
        'class_name': o.__class__.__name__,
        'config': o.get_config()
    }
    return config


def huber_loss(y_true, y_pred, clip_value):
    # Huber loss, see https://en.wikipedia.org/wiki/Huber_loss and
    # https://medium.com/@karpathy/yes-you-should-understand-backprop-e2f06eab496b
    # for details.
    assert clip_value > 0.

    x = y_true - y_pred
    if np.isinf(clip_value):
        # Spacial case for infinity since Tensorflow does have problems
        # if we compare `K.abs(x) < np.inf`.
        return .5 * K.square(x)

    condition = K.abs(x) < clip_value
    squared_loss = .5 * K.square(x)
    linear_loss = clip_value * (K.abs(x) - .5 * clip_value)
    if K.backend() == 'tensorflow':
        import tensorflow as tf
        if hasattr(tf, 'select'):
            return tf.select(condition, squared_loss, linear_loss)  # condition, true, false
        else:
            return tf.where(condition, squared_loss, linear_loss)  # condition, true, false
    elif K.backend() == 'theano':
        from theano import tensor as T
        return T.switch(condition, squared_loss, linear_loss)
    else:
        raise RuntimeError('Unknown backend "{}".'.format(K.backend()))


def GeneralizedAdvantageEstimator(critic, state_batch, reward, gamma, lamb):
    """
    Compute the Generalized Advantage Estimator.

    See https://danieltakeshi.github.io/2017/04/02/notes-on-the-generalized-advantage-estimation-paper/

    :param critic: Critic network.
    :param state_batch: A numpy array of batched input that can be feed into the critic network directly. Note that it must also contain the ending state, i.e. has batch_size + 1 entries.
    :param reward: numpy array of shape (batch_size,)
    :param gamma: Tuning parameter gamma.
    :param lamb: Tuning parameter lambda.
    :return: Python List of GAE values in ascending time order (matched with parameter reward)
    """
    n = len(state_batch) - 1
    assert reward.shape == (n,)
    value = critic.predict_on_batch(state_batch).flatten()
    delta = reward + gamma * value[1:, ] - value[:-1, ]
    # No premature optimization for now...
    result = [0]
    r = gamma * lamb
    for i in range(0, n):
        result.append(result[-1] * r + delta[n-1-i])
    return result[:0:-1]


class AdditionalUpdatesOptimizer(optimizers.Optimizer):
    def __init__(self, optimizer, additional_updates):
        super(AdditionalUpdatesOptimizer, self).__init__()
        self.optimizer = optimizer
        self.additional_updates = additional_updates

    def get_updates(self, params, constraints, loss):
        updates = self.optimizer.get_updates(params, constraints, loss)
        updates += self.additional_updates
        self.updates = updates
        return self.updates

    def get_config(self):
        return self.optimizer.get_config()

def state_windowing(states, window_len):
    def naive_pad(x, shift, axis=0):
        y = np.roll(x, shift, axis)
        y[0:shift, ] = 0
        return y

    return np.stack( [ naive_pad(states, i, axis=0) for i in reversed(range(window_len))], axis=1 )
