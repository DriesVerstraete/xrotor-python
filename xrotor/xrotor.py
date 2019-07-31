# -*- coding: utf-8 -*-
#   Copyright (c) 2018 D. de Vries
#
#   This file is part of XRotor.
#
#   XRotor is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   XRotor is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with XRotor.  If not, see <https://www.gnu.org/licenses/>.
import numpy as np
import os
import glob
import ctypes

from ctypes import c_bool, c_int, byref, POINTER, c_float, cdll
from shutil import copy2
from tempfile import NamedTemporaryFile

from .model import Case, Performance

here = os.path.abspath(os.path.dirname(__file__))
lib_path = glob.glob(os.path.join(here, 'libxrotor.*'))[0]
lib_ext = lib_path[lib_path.rfind('.'):]
fptr = POINTER(c_float)


class XRotor(object):
    """Interface to the XRotor Fortran routines.

    Attributes
    ----------
    print
    max_iter
    case
    performance
    station_conditions
    rms
    """

    def __init__(self):
        super().__init__()
        tmp = NamedTemporaryFile(mode='wb', delete=False, suffix=lib_ext)
        tmp.close()
        self._lib_path = tmp.name
        copy2(lib_path, self._lib_path)
        self._lib = cdll.LoadLibrary(self._lib_path)

        self._lib.get_print.restype = c_bool
        self._lib.operate.restype = c_float
        self._lib.get_rms.restype = c_float
        self._lib.get_blade_angle_change.restype = c_float

        self._lib.init()
        self._case: Case = None

    def __del__(self):
        handle = self._lib._handle
        del self._lib
        try:
            ctypes.windll.kernel32.FreeLibrary(handle)
        except AttributeError:
            pass
        finally:
            os.remove(self._lib_path)

    @property
    def print(self):
        """bool: True if console output should be shown."""
        return self._lib.get_print()

    @print.setter
    def print(self, value):
        self._lib.set_print(byref(c_bool(value)))

    @property
    def max_iter(self):
        """integer: Maximum number of iterations."""
        return self._lib.get_max_iter()

    @max_iter.setter
    def max_iter(self, value):
        self._lib.set_max_iter(byref(c_int(value)))

    @property
    def case(self) -> Case:
        """Case: XRotor run case specification"""
        return self._case

    @case.setter
    def case(self, case: Case):
        self._case = case
        self._lib.set_case(
            byref(c_float(case.conditions.rho)),
            byref(c_float(case.conditions.vso)),
            byref(c_float(case.conditions.rmu)),
            byref(c_float(case.conditions.alt)),
            byref(c_float(case.conditions.vel)),
            byref(c_float(case.conditions.adv)),
            byref(c_float(case.disk.blade.geometry.r_hub)),
            byref(c_float(case.disk.blade.geometry.r_tip)),
            byref(c_float(case.disk.blade.geometry.r_wake)),
            byref(c_float(case.disk.blade.geometry.rake)),
            byref(c_int(case.disk.n_blds)),
            byref(c_int(case.disk.blade.n_aero)),
            byref(c_int(case.disk.blade.geometry.n_geom)),
            np.asfortranarray(case.disk.blade.aerodata).ctypes.data_as(fptr),
            np.asfortranarray(case.disk.blade.geomdata).ctypes.data_as(fptr),
            byref(c_bool(case.settings.free)),
            byref(c_bool(case.settings.duct)),
            byref(c_bool(case.settings.wind))
        )

    @property
    def performance(self) -> Performance:
        """Performance: Propeller performance specification"""
        perf = Performance()
        self._lib.get_performance(
            byref(perf._rpm), byref(perf._thrust), byref(perf._torque), byref(perf._power), byref(perf._efficiency)
        )
        return perf

    @property
    def station_conditions(self):
        """(np.ndarray, np.ndarray): Normalized radial coordinates and corresponding local Reynolds numbers."""
        n = self._lib.get_number_of_stations()
        xi = np.zeros(n, dtype=c_float, order='F')
        re = np.zeros(n, dtype=c_float, order='F')
        self._lib.get_station_conditions(byref(c_int(n)), xi.ctypes.data_as(fptr), re.ctypes.data_as(fptr))
        return xi, re

    @property
    def rms(self):
        """float: The root-mean-squared error of the last XRotor analysis."""
        return float(self._lib.get_rms())

    def operate(self, thrust=None, torque=None, power=None, rpm=None):
        """Operate the propeller at a specified thrust, torque, power, or rpm.

        When only only one parameter is specified, the blade pitch will be left unchanged.
        If thrust, torque, or power is given along with rpm, the blade pitch will be varied and the rpm constrained.

        Parameters
        ----------
        thrust : float
            Thrust in N
        torque : float
            Torque in Nm
        power : float
            Power in W
        rpm : float
            Rotational speed in rev/s

        Returns
        -------
        rms : float
            Root-mean-squared error of after last XRotor iteration.
        blade_angle_change : float, optional
            Blade angle change in degrees, if the rpm is constrained for given thrust, torque, or power.
        """
        if thrust is not None and torque is not None and power is not None:
            raise ValueError('Thrust, torque, and power cannot be specified simultaneously.')
        if thrust is not None and torque is not None:
            raise ValueError('Thrust and torque cannot be specified simultaneously.')
        if thrust is not None and power is not None:
            raise ValueError('Thrust and power cannot be specified simultaneously.')

        if thrust is not None:
            if rpm is not None:
                rms = self._lib.operate(byref(c_int(1)), byref(c_float(thrust)), byref(c_int(1)), byref(c_float(rpm)))
                blade_angle_change = self._lib.get_blade_angle_change()
                return rms, blade_angle_change
            else:
                return self._lib.operate(byref(c_int(1)), byref(c_float(thrust)), byref(c_int(2)), None)
        elif torque is not None:
            if rpm is not None:
                rms = self._lib.operate(byref(c_int(2)), byref(c_float(torque)), byref(c_int(1)), byref(c_float(rpm)))
                blade_angle_change = self._lib.get_blade_angle_change()
                return rms, blade_angle_change
            else:
                return self._lib.operate(byref(c_int(2)), byref(c_float(torque)), byref(c_int(2)), None)
        elif power is not None:
            if rpm is not None:
                rms = self._lib.operate(byref(c_int(3)), byref(c_float(power)), byref(c_int(1)), byref(c_float(rpm)))
                blade_angle_change = self._lib.get_blade_angle_change()
                return rms, blade_angle_change
            else:
                return self._lib.operate(byref(c_int(3)), byref(c_float(power)), byref(c_int(2)), None)
        elif rpm is not None:
            return self._lib.operate(byref(c_int(4)), byref(c_float(rpm)), None, None)
        else:
            raise ValueError('Neither thrust, torque, power, or rpm was provided.')

    def print_case(self):
        """Print the characteristics of the run case at the last operating point to the terminal."""
        self._lib.show()
