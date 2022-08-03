"""Routines and classes for estimation of observables."""

from __future__ import print_function

import copy
import os
import time
import warnings

import h5py
import numpy
import scipy.linalg

from ipie.estimators.energy import EnergyEstimator
from ipie.estimators.utils import H5EstimatorHelper
from ipie.utils.io import get_input_value

# Some supported (non-custom) estimators
_predefined_estimators = {
        'energy': EnergyEstimator,
        }


class EstimatorHandler(object):
    """Container for qmc options of observables.

    Parameters
    ----------
    comm : MPI.COMM_WORLD
        MPI Communicator
    qmc : :class:`ipie.state.QMCOpts` object.
        Container for qmc input options.
    system : :class:`ipie.hubbard.Hubbard` / system object in general.
        Container for model input options.
    trial : :class:`ipie.trial_wavefunction.X' object
        Trial wavefunction class.
    verbose : bool
        If true we print out additional setup information.
    options: dict
        input options detailing which estimators to calculate. By default only
        mixed options will be calculated.

    Attributes
    ----------
    estimators : dict
        Dictionary of estimator objects.
    """

    def __init__(
        self,
        comm,
        qmc,
        system,
        hamiltonian,
        trial,
        options={},
        verbose=False
    ):
        if verbose:
            print("# Setting up estimator object.")
        if comm.rank == 0:
            self.index = options.get("index", 0)
            self.filename = options.get("filename", None)
            self.basename = options.get("basename", "options")
            if self.filename is None:
                overwrite = options.get("overwrite", True)
                self.filename = self.basename + ".%s.h5" % self.index
                while os.path.isfile(self.filename) and not overwrite:
                    self.index = int(self.filename.split(".")[1])
                    self.index = self.index + 1
                    self.filename = self.basename + ".%s.h5" % self.index
            with h5py.File(self.filename, "w") as fh5:
                pass
            if verbose:
                print("# Writing estimator data to {}.".format(self.filename))
        else:
            self.filename = None
        observables = options.get("observables", {"energy": {}})
        self.estimators = {}
        for obs, obs_dict in observables.items():
            try:
                self.estimators[obs] = (
                        predefined_estimators[obs](
                            comm=comm,
                            qmc=qmc,
                            system=system,
                            ham=hamiltonian,
                            trial=trial,
                            options=obs_dict
                            )
                        )
            except KeyError:
                raise RuntimeError(f"unknown observable: {obs}")
        if verbose:
            print("# Finished settting up estimator object.")

    def dump_metadata(self):
        with h5py.File(self.filename, "a") as fh5:
            fh5["metadata"] = self.json_string

    def increment_file_number(self):
        self.index = self.index + 1
        self.filename = self.basename + ".%s.h5" % self.index

    def setup_output(self, comm):
        if comm.rank == 0:
            for k, e in self.estimators.items():
                self.output = H5EstimatorHelper(self.filename,
                        chunk_size=self.buffer_size,
                        shape=(self.estimators.total_size,)
                        )

    def compute_estimators(
        self, comm, system, hamiltonian, trial, walker_batch
    ):
        """Update estimators with bached psi

        Parameters
        ----------
        """
        # Compute all estimators
        # For the moment only consider estimators compute per block.
        # TODO: generalize for different block groups (loop over groups)
        for k, e in self.estimators.items():
            estimator_slice = self.estimators[k].slice
            self.local_estimates[estimator_slice] = (
                e.compute_estimators(qmc, system, walker_batch, hamiltonian, trial)
                )
        comm.Reduce(self.local_estimates, self.global_estimates, op=MPI.SUM)
        output_string = ''
        for k, e in self.estimators.items():
            e.post_reduce_hook(self.global_estimates)
            if comm.rank == 0:
                self.output.push_to_chunk(
                        self.global_estimates,
                        f"data_{e.write_frequency}")
                self.output.increment()
            if e.print_to_stdout:
                pass
        self.zero()

# TODO: Will have to take block index if we ever accumulate things on longer
# time scale
def EstimatorHelper(object):
    """Smaller wrapper around dict that stores shapes."""

    def __init__(self):
        self._estimators = {}
        self._shapes = []
        self._offset = {}
        self._num_estim = 0

    def push(name: str, estimator: EstimatorBase) -> None:
        self._estimators[name] = estimator
        shape = estimator.shape
        self._shapes.append(estimator.shape)
        self._num_estim += 1
        prev_obs = self._offsets.items()[-1]
        offset = np.prod(shape) + self._offsets[pre_obs]
        self._offsets.append(offset)

    @property
    def offset(name: str) -> int:
        offset = self._offsets.get(name)
        assert offset is not None, f"Unknown estimator name {name}"
        return offset
