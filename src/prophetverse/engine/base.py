"""Numpyro inference engines for prophet models.

The classes in this module take a model, the data and perform inference using Numpyro.
"""

from typing import Callable

import jax
from skbase.base import BaseObject

from prophetverse.utils.deprecation import deprecation_warning

_DEFAULT_PREDICT_NUM_SAMPLES = 1000


class BaseInferenceEngine(BaseObject):
    """
    Class representing an inference engine for a given model.

    Parameters
    ----------
    model : Callable
        The model to be used for inference.
    rng_key : Optional[jax.random.PRNGKey]
        The random number generator key. If not provided, a default key with value 0
        will be used.

    Attributes
    ----------
    model : Callable
        The model used for inference.
    rng_key : jax.random.PRNGKey
        The random number generator key.
    """

    _tags = {
        "object_type": "inference_engine",
    }

    def __init__(self, model: Callable, rng_key=None):
        self.model = model
        self.rng_key = rng_key

        if rng_key is None:
            rng_key = jax.random.PRNGKey(0)
        self._rng_key = rng_key

    # pragma: no cover
    def infer(self, **kwargs):
        """
        Perform inference using the specified model.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to be passed to the model.

        Returns
        -------
        The result of the inference.
        """
        raise NotImplementedError("infer method must be implemented in subclass")

    # pragma: no cover
    def predict(self, **kwargs):
        """
        Generate predictions using the specified model.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to be passed to the model.

        Returns
        -------
        The predictions generated by the model.
        """
        raise NotImplementedError("predict method must be implemented in subclass")


# TODO: remove this class in 0.6 release
class InferenceEngine(BaseInferenceEngine):
    """Temporary class to handle deprecation of InferenceEngine."""

    def __init__(self, model: Callable, rng_key=None):
        deprecation_warning("InferenceEngine", "0.4.1")
        super().__init__(model, rng_key)
