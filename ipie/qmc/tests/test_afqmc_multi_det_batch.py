import numpy
from mpi4py import MPI
import os
import pytest
from ipie.analysis.extraction import (
        extract_mixed_estimates,
        extract_rdm
        )
from ipie.qmc.calc import setup_calculation
from ipie.qmc.afqmc_batch import AFQMCBatch

from ipie.legacy.qmc.afqmc import AFQMC
from ipie.legacy.hamiltonians.generic import Generic as LegacyHamGeneric
from ipie.legacy.trial_wavefunction.multi_slater import MultiSlater as LegacyMultiSlater

from ipie.systems.generic import Generic
from ipie.hamiltonians.generic import Generic as HamGeneric
from ipie.trial_wavefunction.multi_slater import MultiSlater
from ipie.utils.testing import generate_hamiltonian, get_random_phmsd
from ipie.utils.pack import pack_cholesky

steps = 25
blocks = 5
seed = 7
nwalkers = 25
nmo = 3
nelec = (2,1)
pop_control_freq = 1
ndets = 5
stabilise_freq = 10

@pytest.mark.driver
def test_generic_multi_det_batch():
    options = {
            'verbosity': 0,
            'get_sha1': False,
            'qmc': {
                'timestep': 0.005,
                'steps': steps,
                'nwalkers_per_task':nwalkers,
                'stabilise_freq': stabilise_freq,
                'pop_control_freq': pop_control_freq,
                'blocks': blocks,
                'rng_seed': seed,
                'batched': True
            },
            'estimates': {
                'mixed': {
                    'energy_eval_freq': 1
                }
            },
            'trial': {
                'name': 'MultiSlater'
            },
            'walkers': {
                'population_control':'pair_branch'
            }
        }
    numpy.random.seed(seed)
    h1e, chol, enuc, eri = generate_hamiltonian(nmo, nelec, cplx=False)
    chol = chol.reshape((-1,nmo*nmo)).T.copy()

    nchol = chol.shape[-1]
    chol = chol.reshape((nmo,nmo,nchol))

    idx = numpy.triu_indices(nmo)
    cp_shape = (nmo*(nmo+1)//2, chol.shape[-1])
    chol_packed = numpy.zeros(cp_shape, dtype = chol.dtype)
    pack_cholesky(idx[0],idx[1], chol_packed, chol)
    chol = chol.reshape((nmo*nmo,nchol))


    sys = Generic(nelec=nelec) 
    ham = HamGeneric(h1e=numpy.array([h1e,h1e]),
                  chol=chol, chol_packed = chol_packed,
                  ecore=enuc)

    wfn, init = get_random_phmsd(sys.nup, sys.ndown, ham.nbasis, ndet=ndets, init=True)
    trial = MultiSlater(sys, ham, wfn, init=init)
    if (ndets == 1):
        trial.half_rotate(sys, ham)
        trial.psi = trial.psi[0]

    numpy.random.seed(seed)

    comm = MPI.COMM_WORLD
    afqmc = AFQMCBatch(comm=comm, system=sys, hamiltonian = ham, trial=trial, options=options)
    afqmc.estimators.estimators['mixed'].print_header()
    afqmc.run(comm=comm, verbose=0)
    afqmc.finalise(verbose=0)
    afqmc.estimators.estimators['mixed'].update_batch(afqmc.qmc, afqmc.system, afqmc.hamiltonian,
                                                afqmc.trial, afqmc.psi.walkers_batch, 0)
    enum_batch = afqmc.estimators.estimators['mixed'].names
    numer_batch = afqmc.estimators.estimators['mixed'].estimates[enum_batch.enumer]
    denom_batch = afqmc.estimators.estimators['mixed'].estimates[enum_batch.edenom]
    weight_batch = afqmc.estimators.estimators['mixed'].estimates[enum_batch.weight]

    data_batch = extract_mixed_estimates('estimates.0.h5')

    numpy.random.seed(seed)
    options = {
            'verbosity': 0,
            'get_sha1': False,
            'qmc': {
                'timestep': 0.005,
                'steps': steps,
                'nwalkers_per_task':nwalkers,
                'stabilise_freq': stabilise_freq,
                'pop_control_freq':pop_control_freq,
                'blocks': blocks,
                'rng_seed': seed,
                'batched': False
            },
            'estimates': {
                'mixed': {
                    'energy_eval_freq': 1
                }
            },
            'trial': {
                'name': 'MultiSlater'
            },
            'walkers': {
                'population_control':'pair_branch'
            }
        }
    numpy.random.seed(seed)
    h1e, chol, enuc, eri = generate_hamiltonian(nmo, nelec, cplx=False)
    sys = Generic(nelec=nelec) 
    ham = LegacyHamGeneric(h1e=numpy.array([h1e,h1e]),
                  chol=chol.reshape((-1,nmo*nmo)).T.copy(),
                  ecore=enuc)

    trial = LegacyMultiSlater(sys, ham, wfn, init=init)
    if (ndets == 1):
        trial.half_rotate(sys, ham)
        trial.psi = trial.psi[0]

    numpy.random.seed(seed)

    comm = MPI.COMM_WORLD
    afqmc = AFQMC(comm=comm, system=sys, hamiltonian = ham, options=options, trial=trial)
    afqmc.estimators.estimators['mixed'].print_header()
    afqmc.run(comm=comm, verbose=0)
    afqmc.finalise(verbose=0)
    afqmc.estimators.estimators['mixed'].update(afqmc.qmc, afqmc.system, afqmc.hamiltonian,
                                                afqmc.trial, afqmc.psi, 0)
    enum = afqmc.estimators.estimators['mixed'].names
    numer = afqmc.estimators.estimators['mixed'].estimates[enum.enumer]
    denom = afqmc.estimators.estimators['mixed'].estimates[enum.edenom]
    weight = afqmc.estimators.estimators['mixed'].estimates[enum.weight]

    assert numer.real == pytest.approx(numer_batch.real)
    assert denom.real == pytest.approx(denom_batch.real)
    assert weight.real == pytest.approx(weight_batch.real)
    assert numer.imag == pytest.approx(numer_batch.imag)
    assert denom.imag == pytest.approx(denom_batch.imag)
    assert weight.imag == pytest.approx(weight_batch.imag)
    data = extract_mixed_estimates('estimates.0.h5')

    assert numpy.mean(data_batch.WeightFactor.values[:-1].real) == pytest.approx(numpy.mean(data.WeightFactor.values[:-1].real))
    assert numpy.mean(data_batch.Weight.values[:-1].real) == pytest.approx(numpy.mean(data.Weight.values[:-1].real))
    assert numpy.mean(data_batch.ENumer.values[:-1].real) == pytest.approx(numpy.mean(data.ENumer.values[:-1].real))
    assert numpy.mean(data_batch.EDenom.values[:-1].real) == pytest.approx(numpy.mean(data.EDenom.values[:-1].real))
    assert numpy.mean(data_batch.ETotal.values[:-1].real) == pytest.approx(numpy.mean(data.ETotal.values[:-1].real))
    assert numpy.mean(data_batch.E1Body.values[:-1].real) == pytest.approx(numpy.mean(data.E1Body.values[:-1].real))
    assert numpy.mean(data_batch.E2Body.values[:-1].real) == pytest.approx(numpy.mean(data.E2Body.values[:-1].real))
    assert numpy.mean(data_batch.EHybrid.values[:-1].real) == pytest.approx(numpy.mean(data.EHybrid.values[:-1].real))
    assert numpy.mean(data_batch.Overlap.values[:-1].real) == pytest.approx(numpy.mean(data.Overlap.values[:-1].real))


if __name__=="__main__":
    test_generic_multi_det_batch()
