"""Numpyro inference engines for prophet models.

The classes in this module take a model, the data and perform inference using Numpyro.
"""

import gc
from typing import Callable

import jax
import jax.numpy as jnp
import numpyro
from numpyro.infer import MCMC, NUTS, SVI, Predictive, Trace_ELBO
from numpyro.infer.autoguide import AutoDelta
from numpyro.infer.initialization import init_to_mean
from numpyro.infer.svi import SVIRunResult

_DEFAULT_PREDICT_NUM_SAMPLES = 1000


class InferenceEngine:
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

    def __init__(self, model: Callable, rng_key=None):
        self.model = model
        if rng_key is None:
            rng_key = jax.random.PRNGKey(0)
        self.rng_key = rng_key

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


class MAPInferenceEngine(InferenceEngine):
    """
    Maximum a Posteriori (MAP) Inference Engine.

    This class performs MAP inference using Stochastic Variational Inference (SVI)
    with AutoDelta guide. It provides methods for inference and prediction.

    Parameters
    ----------
    model : Callable
        The probabilistic model to perform inference on.
    optimizer_factory : numpyro.optim._NumPyroOptim, optional
        The optimizer to use for SVI. Defaults to None.
    num_steps : int, optional
        The number of optimization steps to perform. Defaults to 10000.
    rng_key : jax.random.PRNGKey, optional
        The random number generator key. Defaults to None.
    """

    def __init__(
        self,
        model: Callable,
        optimizer_factory: numpyro.optim._NumPyroOptim = None,
        num_steps=10000,
        num_samples=_DEFAULT_PREDICT_NUM_SAMPLES,
        rng_key=None,
    ):
        if optimizer_factory is None:
            optimizer_factory = self.default_optimizer_factory
        self.optimizer_factory = optimizer_factory
        self.num_steps = num_steps
        self.num_samples = num_samples
        super().__init__(model, rng_key)

    def default_optimizer_factory(self):
        """Create the default optimizer for SVI."""
        return numpyro.optim.Adam(step_size=0.001)

    def infer(self, **kwargs):
        """
        Perform MAP inference.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to be passed to the model.

        Returns
        -------
        self
            The updated MAPInferenceEngine object.
        """
        self.guide_ = AutoDelta(self.model, init_loc_fn=init_to_mean())

        def get_result(rng_key, model, guide, optimizer, num_steps, **kwargs):
            svi_ = SVI(model, guide, optimizer, loss=Trace_ELBO())
            return svi_.run(rng_key=rng_key, num_steps=num_steps, **kwargs)

        self.run_results_: SVIRunResult = get_result(
            self.rng_key,
            self.model,
            self.guide_,
            self.optimizer_factory(),
            self.num_steps,
            **kwargs
        )

        gc.collect()
        jax.clear_caches()

        self.raise_error_if_nan_loss(self.run_results_)

        self.posterior_samples_ = self.guide_.sample_posterior(
            self.rng_key, params=self.run_results_.params, **kwargs
        )
        return self

    def raise_error_if_nan_loss(self, run_results: SVIRunResult):
        """
        Raise an error if the loss is NaN.

        Parameters
        ----------
        run_results : SVIRunResult
            The result of the SVI run.

        Raises
        ------
        MAPInferenceEngineError
            If the last loss is NaN.
        """
        losses = run_results.losses
        if jnp.isnan(losses)[-1]:
            msg = "NaN losses in MAPInferenceEngine."
            msg += " Try decreasing the learning rate or changing the model specs."
            msg += " If the problem persists, please open an issue at"
            msg += " https://github.com/felipeangelimvieira/prophetverse"
            raise MAPInferenceEngineError(msg)

    def predict(self, **kwargs):
        """
        Generate predictions using the trained model.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to be passed to the model.

        Returns
        -------
        numpyro.samples_
            The predicted samples generated by the model.
        """
        predictive = numpyro.infer.Predictive(
            self.model,
            params=self.run_results_.params,
            guide=self.guide_,
            # posterior_samples=self.posterior_samples_,
            num_samples=self.num_samples,
        )
        numpyro.samples_ = predictive(rng_key=self.rng_key, **kwargs)
        return numpyro.samples_


class MCMCInferenceEngine(InferenceEngine):
    """
    Perform MCMC (Markov Chain Monte Carlo) inference for a given model.

    Parameters
    ----------
    model : Callable
        The model function to perform inference on.
    num_samples : int
        The number of MCMC samples to draw.
    num_warmup : int
        The number of warmup samples to discard.
    num_chains : int
        The number of MCMC chains to run in parallel.
    dense_mass : bool
        Whether to use dense mass matrix for NUTS sampler.
    rng_key : Optional
        The random number generator key.

    Attributes
    ----------
    num_samples : int
        The number of MCMC samples to draw.
    num_warmup : int
        The number of warmup samples to discard.
    num_chains : int
        The number of MCMC chains to run in parallel.
    dense_mass : bool
        Whether to use dense mass matrix for NUTS sampler.
    mcmc_ : MCMC
        The MCMC object used for inference.
    posterior_samples_ : Dict[str, np.ndarray]
        The posterior samples obtained from MCMC.
    samples_predictive_ : Dict[str, np.ndarray]
        The predictive samples obtained from MCMC.
    samples_ : Dict[str, np.ndarray]
        The MCMC samples obtained from MCMC.
    """

    def __init__(
        self,
        model: Callable,
        num_samples=1000,
        num_warmup=200,
        num_chains=1,
        dense_mass=False,
        rng_key=None,
    ):
        self.num_samples = num_samples
        self.num_warmup = num_warmup
        self.num_chains = num_chains
        self.dense_mass = dense_mass
        super().__init__(model, rng_key)

    def infer(self, **kwargs):
        """
        Run MCMC inference.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to be passed to the MCMC run method.

        Returns
        -------
        self
            The MCMCInferenceEngine object.
        """
        self.mcmc_ = MCMC(
            NUTS(self.model, dense_mass=self.dense_mass, init_strategy=init_to_mean()),
            num_samples=self.num_samples,
            num_warmup=self.num_warmup,
        )
        self.mcmc_.run(self.rng_key, **kwargs)
        self.posterior_samples_ = self.mcmc_.get_samples()
        return self

    def predict(self, **kwargs):
        """
        Generate predictive samples.

        Parameters
        ----------
        **kwargs
            Additional keyword arguments to be passed to the Predictive method.

        Returns
        -------
        Dict[str, np.ndarray]
            The predictive samples.
        """
        predictive = Predictive(
            self.model, self.posterior_samples_, num_samples=self.num_samples
        )

        numpyro.samples_predictive_ = predictive(self.rng_key, **kwargs)
        numpyro.samples_ = self.mcmc_.get_samples()
        return numpyro.samples_predictive_


class MAPInferenceEngineError(Exception):
    """Exception raised for NaN losses in MAPInferenceEngine."""

    def __init__(self, message="NaN losses in MAPInferenceEngine"):
        self.message = message
        super().__init__(self.message)
