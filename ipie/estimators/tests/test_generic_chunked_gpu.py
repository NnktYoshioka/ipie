import numpy
import pytest
from mpi4py import MPI

try:
    import cupy
    no_gpu = not cupy.is_available()
except:
    no_gpu = True

from ipie.estimators.generic import local_energy_cholesky_opt
from ipie.estimators.local_energy_sd import (local_energy_single_det_batch,
                                             local_energy_single_det_batch_gpu,
                                             local_energy_single_det_rhf_batch,
                                             local_energy_single_det_uhf_batch)
from ipie.estimators.local_energy_sd_chunked import (
    local_energy_single_det_uhf_batch_chunked,
    local_energy_single_det_uhf_batch_chunked_gpu)
from ipie.hamiltonians.generic import Generic as HamGeneric
from ipie.propagation.continuous import Continuous
from ipie.systems.generic import Generic
from ipie.trial_wavefunction.multi_slater import MultiSlater
from ipie.utils.misc import dotdict, is_cupy
from ipie.utils.mpi import MPIHandler, get_shared_array, have_shared_mem
from ipie.utils.pack import pack_cholesky
from ipie.utils.testing import generate_hamiltonian, get_random_nomsd
from ipie.walkers.single_det_batch import SingleDetWalkerBatch

comm = MPI.COMM_WORLD
size = comm.Get_size()
rank = comm.Get_rank()

numpy.random.seed(7)
skip = comm.size == 1


@pytest.mark.unit
@pytest.mark.skipif(skip, reason="Test should be run on multiple cores.")
@pytest.mark.skipif(no_gpu, reason="gpu not found.")
def test_generic_chunked_gpu():
    nwalkers = 50
    nsteps = 20
    numpy.random.seed(7)
    nmo = 24
    nelec = (4, 2)
    h1e, chol, enuc, eri = generate_hamiltonian(nmo, nelec, cplx=False)

    h1e = comm.bcast(h1e)
    chol = comm.bcast(chol)
    enuc = comm.bcast(enuc)
    eri = comm.bcast(eri)

    chol = chol.reshape((-1, nmo * nmo)).T.copy()

    nchol = chol.shape[-1]
    chol = chol.reshape((nmo, nmo, nchol))

    idx = numpy.triu_indices(nmo)
    cp_shape = (nmo * (nmo + 1) // 2, chol.shape[-1])
    # chol_packed = numpy.zeros(cp_shape, dtype = chol.dtype)
    chol_packed = get_shared_array(comm, cp_shape, chol.dtype)

    if comm.rank == 0:
        pack_cholesky(idx[0], idx[1], chol_packed, chol)

    chol = chol.reshape((nmo * nmo, nchol))

    system = Generic(nelec=nelec)
    ham = HamGeneric(
        h1e=numpy.array([h1e, h1e]), chol=chol, chol_packed=chol_packed, ecore=enuc
    )
    wfn = get_random_nomsd(system.nup, system.ndown, ham.nbasis, ndet=1, cplx=False)
    trial = MultiSlater(system, ham, wfn)
    trial.half_rotate(system, ham)

    trial.psi = trial.psi[0]
    trial.psia = trial.psia[0]
    trial.psib = trial.psib[0]
    trial.calculate_energy(system, ham)

    qmc = dotdict({"dt": 0.005, "nstblz": 5, "batched": True, "nwalkers": nwalkers})
    options = {"hybrid": True}
    prop = Continuous(system, ham, trial, qmc, options=options)

    mpi_handler = MPIHandler(comm, options={"nmembers": 2}, verbose=(rank == 0))
    if comm.rank == 0:
        print("# Chunking hamiltonian.")
    ham.chunk(mpi_handler)
    if comm.rank == 0:
        print("# Chunking trial.")
    trial.chunk(mpi_handler)

    walker_batch = SingleDetWalkerBatch(
        system, ham, trial, nwalkers, mpi_handler=mpi_handler
    )

    if not no_gpu:
        prop.cast_to_cupy()
        ham.cast_to_cupy()
        trial.cast_to_cupy()
        walker_batch.cast_to_cupy()

    for i in range(nsteps):
        prop.propagate_walker_batch(walker_batch, system, ham, trial, trial.energy)
        walker_batch.reortho()

    trial._rchola = cupy.asarray(trial._rchola)
    trial._rcholb = cupy.asarray(trial._rcholb)
    energies_einsum = local_energy_single_det_batch_gpu(
        system, ham, walker_batch, trial
    )
    energies_chunked = local_energy_single_det_uhf_batch_chunked_gpu(
        system, ham, walker_batch, trial
    )
    energies_chunked_low_mem = local_energy_single_det_uhf_batch_chunked_gpu(
        system, ham, walker_batch, trial, max_mem=1e-6
    )

    assert numpy.allclose(energies_einsum, energies_chunked)
    assert numpy.allclose(energies_einsum, energies_chunked_low_mem)

if __name__ == "__main__":
    test_generic_chunked_gpu()
