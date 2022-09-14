#!/usr/bin/env python3

import argparse
import json
import sys

from mpi4py import MPI

import ipie
from ipie.config import config


def parse_args(args, comm):
    """Parse command-line arguments.

    Parameters
    ----------
    args : list of strings
        command-line arguments.

    Returns
    -------
    options : :class:`argparse.ArgumentParser`
        Command line arguments.
    """

    if comm.rank == 0:
        parser = argparse.ArgumentParser(description = __doc__)
        parser.add_argument('--gpu', dest='use_gpu', action="store_true",
                            help='Use GPU.')
        parser.add_argument('remaining_options', nargs=argparse.REMAINDER)
        options = parser.parse_args(args)
    else:
        options = None
    options = comm.bcast(options, root=0)

    if len(options.remaining_options) != 1:
        if comm.rank == 0:
            parser.print_help()
        sys.exit()

    return options



def main(input_file):
    """Simple launcher for ipie via input file.

    Parameters
    ----------
    input_file : string
        JSON input file name.
    """
    comm = MPI.COMM_WORLD
    options = parse_args(sys.argv[1:], comm)
    config.update_option("use_gpu", options.use_gpu)
    from ipie.qmc.calc import setup_calculation
    (afqmc, comm) = setup_calculation(options.remaining_options[0])
    afqmc.run(comm=comm, verbose=True)
    afqmc.finalise(verbose=True)


if __name__ == '__main__':
    main(sys.argv[1])
