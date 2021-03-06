#!/usr/bin/python
import sys

import sqlite3
import numpy as np
import copy

class SurfaceCode:

    """
       This class describes a square surface code with an odd distance 3,5,7,...

      Input
      -----

      seed -- a seed to initialize the random number generator
      git_version -- git version of this file, if it is not available the default
                     is set to zero
      distance -- the distance of the surface code
      pqx, pqy, pqz -- error rates on the data qubits (per circuit element)
      pax, pay, paz -- error rates on the ancilla qubits (per circuit element)
      pm -- measurement errors applied at both ancilla and data qubit readouts
      """

    def __init__(
        self,
        seed,
        git_version=0,
        distance=3,
        pqx=0,
        pqy=0,
        pqz=0,
        pax=0,
        pay=0,
        paz=0,
        pm=0):

        # # # Git version and seed # # #

        self.git_version = git_version
        self.seed = seed

        # # # Create an instance of random # # #

        self.rng = np.random.RandomState(self.seed)

        # # # Set variables # # #

        self.dist = distance
        self.n_data = self.dist * self.dist  # number of data qubits
        self.n_anc = self.n_data - 1  # number of ancilla (anc) qubits
        self.n_z_stab = int(self.n_anc / 2)  # number of z-stabilizers
        (self.pqx, self.pqy, self.pqz) = (pqx, pqy, pqz)
        (self.pax, self.pay, self.paz) = (pax, pay, paz)
        self.pm = pm

        # # # Initialize data and ancilla qubits # # #

        self._init_qubits()

        # # # Initialize CNOT gates # # #

        self._init_cnots()

    def _init_qubits(self):
        """ This function initializes both ancilla and data qubits. It also
        creates lists with the positions of all data, x-ancilla, and z-ancilla
        qubits.

        Each qubit is defined by two booleans (bitflip-error, phaseflip-error),
        i.e. 00 - no error, 10 - x-error, 11 - y-error, 01 - z-error.
        """

        # Initialize arrays to hold the error information. The qubits will be
        # arranged in the geometry of the surface code.

        self.data_qubits = np.zeros(shape=[self.dist, self.dist, 2],
                                    dtype=bool)
        self.anc_qubits = np.zeros(shape=[self.dist + 1, self.dist + 1,
                                   2], dtype=bool)

        # Generate lists with qubit positions.

        self.data_l = [(m, n) for m in range(self.dist) for n in
                       range(self.dist)]
        (self.x_anc_l, self.z_anc_l) = ([], [])
        for m in range(self.dist + 1):
            for n in range(self.dist + 1):
                if self._anc_exists(m, n):
                    if np.mod(m + n, 2) == 0:
                        self.x_anc_l.append((m, n))
                    else:
                        self.z_anc_l.append((m, n))

        # To produce small outputs, we can condense the matrix of ancilla qubits
        # into a one dimensional vector. Here we do this, and create some meta
        # information about which ancillas in this list correspond to x- and
        # which to z-stabilizer measurements.

        self.anc_l = list(sorted(self.x_anc_l)) \
            + list(sorted(self.z_anc_l))
        (self.x_indcs, self.z_indcs) = ([], [])
        for ncond in range(len(self.anc_l)):
            if self.anc_l[ncond] in self.x_anc_l:
                self.x_indcs.append(ncond)
            elif self.anc_l[ncond] in self.z_anc_l:
                self.z_indcs.append(ncond)
            else:
                raise ValueError('ancilla is neither x- nor z')
            ncond += 1

    def _init_cnots(self):
        """ This function builds dictionaries that describe which ancilla
        qubits are coupled to which data qubits by the different CNOT gates.
        These gates are called North, East, South, and West in a cyclic manner
        starting from the top right corner.

        This function also calculates a dictionary with all the connections
        between z-ancillas and data qubits via the 4 CNOT gates. This is later
        used to calculate the final stabilizer from the data qubit measurement.
        """

        # Get and set the CNOT dictionaries

        (self.x_north_dict, self.x_east_dict, self.x_south_dict,
         self.x_west_dict) = self._make_cnots(self.x_anc_l)
        (self.z_north_dict, self.z_east_dict, self.z_south_dict,
         self.z_west_dict) = self._make_cnots(self.z_anc_l)

        # All connections of z-ancillas to data qubits form a dictionary where the
        # keys are the z-ancilla positions and the entries are lists with all the
        # data qubits that are connected to the corresponding ancilla qubit via
        # the CNOT gates

        self.z_anc_data_conn = {}
        for qb in self.z_anc_l:
            self.z_anc_data_conn[qb] = list()
        for qb in self.z_north_dict.keys():
            self.z_anc_data_conn[qb].append(self.z_north_dict[qb])
        for qb in self.z_east_dict.keys():
            self.z_anc_data_conn[qb].append(self.z_east_dict[qb])
        for qb in self.z_south_dict.keys():
            self.z_anc_data_conn[qb].append(self.z_south_dict[qb])
        for qb in self.z_west_dict.keys():
            self.z_anc_data_conn[qb].append(self.z_west_dict[qb])

    def _reinitialize(self, seed):
        """ This function reinitializes the qubits and sets a new seed.

        Input
        -----
        seed - a new seed for the random number generator
        """

        # Reinitialize random number generator

        self.seed = seed
        self.rng = np.random.RandomState(seed)

        # Reinitialize qubits

        self.data_qubits = np.zeros(shape=[self.dist, self.dist, 2],
                                    dtype=bool)
        self.anc_qubits = np.zeros(shape=[self.dist + 1, self.dist + 1,
                                   2], dtype=bool)

    def _make_cnots(self, anc_l):
        """ This function, given a list of ancilla qubit positions, returns
        four dictionaries which describe how the ancilla qubits are connected
        to the data qubits via the four CNOT gates.

        Input
        -----
        anc_l -- list of ancilla qubit positions

        Output
        ------
        north_dict, east_dict, south_dict, west_dict -- four dictionaries,
        that describe how the ancillas are connected to data qubits for a
        given CNOT gate in the order north, east, south, west
        """

        (north_dict, east_dict, south_dict, west_dict) = ({}, {}, {},
                {})
        for (m, n) in anc_l:
            if m > 0 and n < self.dist:
                north_dict[(m, n)] = (m - 1, n)
            if m < self.dist and n < self.dist:
                east_dict[(m, n)] = (m, n)
            if m < self.dist and n > 0:
                south_dict[(m, n)] = (m, n - 1)
            if m > 0 and n > 0:
                west_dict[(m, n)] = (m - 1, n - 1)
        return (north_dict, east_dict, south_dict, west_dict)

    def _do_step_1(self):
        """ This function executes the first step of the circuit model. During
        this step the x-ancillas undergo a Hadamard rotation, the z-ancillas
        idle. Both, data- and ancilla qubits experience uncorrelated errors.
        """

        # Apply a Hadamard gate on the x-ancillas

        self._hadamard_on_x_ancs()

        # Apply uncorrelated errors to all qubits

        self._apply_uncorr_errs(self.x_anc_l + self.z_anc_l, 'anc')
        self._apply_uncorr_errs(self.data_l, 'data')

    def _do_step_2(self):
        """ This function executes the second step of the circuit model. During
        this step North CNOT gates are applied to the x-ancillas, and North
        CNOT gates are applied to the z-ancillas.
        """

        self._do_cnot_step(self.x_north_dict, self.z_north_dict)

    def _do_step_3(self):
        """ This function executes the third step of the circuit model. During
        this step West CNOT gates are applied to the x-ancillas, and East CNOT
        gates are applied to the z-ancillas.
        """

        self._do_cnot_step(self.x_west_dict, self.z_east_dict)

    def _do_step_4(self):
        """ This function executes the fourth step of the circuit model. During
        this step East CNOT gates are applied to the x-ancillas, and West CNOT
        gates are applied to the z-ancillas.
        """

        self._do_cnot_step(self.x_east_dict, self.z_west_dict)

    def _do_step_5(self):
        """ This function executes the fifth step of the circuit model. During
        this step South CNOT gates are applied to the x-ancillas, and South
        CNOT gates are applied to the z-ancillas.
        """

        self._do_cnot_step(self.x_south_dict, self.z_south_dict)

    def _do_step_6(self):
        """ This function executes the sixth step of the circuit model. It is the
        same as the first step. """

        self._do_step_1()

    def _do_measure_step(self):
        """ This function executes the seventh step. During this step the ancilla
        qubits are are measured (with measurement errors). The measurement
        collapses the wave functions of the ancilla qubits, and the information
        about phaseflip errors is lost (reset). The data qubits idle and
        experience uncorrelated errors.

        Output
        ------
        stabs -- measurement of the stabilizers (=ancilla qubits, =syndrome)
        """

        # Measure the ancilla qubits (i.e. the bit flip errors)

        stabs = copy.copy(self.anc_qubits[:, :, 0])

        # Apply measurement errors

        for qb in self.x_anc_l + self.z_anc_l:
            if self.rng.rand() < self.pm:
                stabs[qb] = not stabs[qb]

        # Reset the phase error information

        self.anc_qubits[:, :, 1] = False

        # The data qubits are idling and experience uncorrelated errors

        self._apply_uncorr_errs(self.data_l, 'data')

        return stabs

    def _do_measure_step_condensed(self):
        """ This function does the same as _do_measure_step, but condenses the
        output (stabilizers) to a list without the dummy ancillas. The ordering is
        according to line m and column n.

        Output
        ------
        stabs_condensed -- measurement of the stabilizers in a condensed list
        """

        stabs = self._do_measure_step()
        stabs_condensed = np.array([stabs[qb] for qb in self.anc_l])
        return stabs_condensed

    def _get_parity_of_bitflips(self):
        """ This function returns the parity of the number of x- and y-errors
            (bitflips) on the data qubits.

        Output
        ------
        parity -- parity of the number of x- and y-errors on the data qubits
        """

        n_xy_errs = 0
        for row in self.data_qubits:
            for el in row:
                if el[0]:
                    n_xy_errs += 1
        parity = bool(np.mod(n_xy_errs, 2))
        return parity

    def _calc_final_z_stabs(self):
        """ This function calculates the final z-stabilizers from the measured
        data-qubits. During the measurement of the data qubits errors occur.
        These errors need to be taken into account when calculating the parity
        of bitflips. The parity of the measurement errors is also returned by
        this function.

        Output
        ------
        z_stabs -- final z-stabilizers
        meas_parity -- parity of measurement errors
        """

        # Measure data qubits (loose phase information)

        data_qubits_meas = copy.copy(self.data_qubits[:, :, 0])

        # Apply measurement errors

        (d1, d2) = np.shape(data_qubits_meas)
        m_errs = self.rng.rand(d1, d2) < self.pm
        data_qubits_meas = np.bitwise_xor(data_qubits_meas, m_errs)
        meas_parity = np.mod(sum(sum(m_errs)), 2)

        # Calculate final stabilizers. The idea is to start with clean
        # ancilla qubits and then flip them for each measured bitflip
        # error on the neighboring data qubits.

        z_stabs = np.zeros(shape=[self.dist + 1, self.dist + 1],
                           dtype=bool)
        for anc_qb in self.z_anc_data_conn.keys():
            data_qb_l = self.z_anc_data_conn[anc_qb]
            for data_qb in data_qb_l:
                if data_qubits_meas[data_qb]:
                    z_stabs[anc_qb] = not z_stabs[anc_qb]

        return (z_stabs, meas_parity)

    def _calc_final_z_stabs_condensed(self):
        """ This function does the same as _calc_final_z_stabs, but
        condenses the output (stabilizers) to a list containing only the
        z-ancillas. The ordering is according to line m and column n.

        Output
        ------
        z_stabs -- final z-stabilizers in a list
        meas_parity -- parity of measurement errors
        """

        (z_stabs, meas_parity) = self._calc_final_z_stabs()
        z_stabs = np.array([z_stabs[qb] for qb in sorted(self.z_anc_l)])
        return (z_stabs, meas_parity)

    def _do_cnot_step(self, x_dict, z_dict):
        """ This function executes one of the CNOT steps. It applies the CNOT
        operations for both ancilla and data qubits.

        Input
        -----
        x-dict -- a dictionary containing the connections set by the CNOT
                  gates between x-ancillas and data qubits
        z-dict -- like x-dict, but for z-ancillas """

        # Apply CNOTS

        self._do_cnots(x_dict, 'x')
        self._do_cnots(z_dict, 'z')

        # Apply uncorrelated errors to all qubits

        self._apply_uncorr_errs(self.x_anc_l + self.z_anc_l, 'anc')
        self._apply_uncorr_errs(self.data_l, 'data')

    def _apply_uncorr_errs(self, qubits, which_qubits):
        """ This function applies uncorrelated errors to the qubits.

        Input
        -----
        qubits -- a list with all the qubits that are subject to uncorrelated
                  errors (must be either all data- or all ancilla-qubits)
        which_qubits -- a string describing the type of qubits in 'qubits':
                        'data' for data qubits, 'anc' for ancilla qubits
        """

        if which_qubits == 'data':
            for qb in qubits:

            # We throw the dice three times for independent x-, y- and z-errors

                rnx = self.rng.rand()
                rny = self.rng.rand()
                rnz = self.rng.rand()
                if rnx < self.pqx:
                    self.data_qubits[qb][0] = \
                        not self.data_qubits[qb][0]
                if rny < self.pqy:
                    self.data_qubits[qb][0] = \
                        not self.data_qubits[qb][0]
                    self.data_qubits[qb][1] = \
                        not self.data_qubits[qb][1]
                if rnz < self.pqz:
                    self.data_qubits[qb][1] = \
                        not self.data_qubits[qb][1]
        elif which_qubits == 'anc':

          # We throw the dice three times for independent x-, y- and z-errors

            for qb in qubits:
                rnx = self.rng.rand()
                rny = self.rng.rand()
                rnz = self.rng.rand()
                if rnx < self.pax:
                    self.anc_qubits[qb][0] = not self.anc_qubits[qb][0]
                if rny < self.pay:
                    self.anc_qubits[qb][0] = not self.anc_qubits[qb][0]
                    self.anc_qubits[qb][1] = not self.anc_qubits[qb][1]
                if rnz < self.paz:
                    self.anc_qubits[qb][1] = not self.anc_qubits[qb][1]
        else:

            raise ValueError("which_qubits must be 'data' or 'anc' but is "
                              + str(which_qubits))

    def _hadamard_on_x_ancs(self):  # test written
        """ This function applies a Hadamard gate to the x-ancillas. This gate
        exchanges bitflip- and phaseflip-errors, i.e. x <--> z errors.
        Y errors get a global phase that we can ignore.
        """

        for qb in self.x_anc_l:
            (e1, e2) = self.anc_qubits[qb]
            self.anc_qubits[qb] = [e2, e1]

    def _do_cnots(self, cnots, which_anc):
        """ This function executes the CNOT gates.
        For x-ancillas: ancilla qubits are control bits, data qubits are
                        target bits
        For z-ancillas: ancilla qubits are target bits, data qubits are
                        control bits

        Input
        -----
        cnots -- a dictionary that describes how the cnots are connecting
                 ancillas and data qubits
        which_anc -- a string, saying whether the CNOTs connect to
                     x- or z-ancillas
        """

        # Figure out what needs to be done

        for anc_qb in cnots.keys():
            data_qb = cnots[anc_qb]
            anc_err = self.anc_qubits[anc_qb]
            data_err = self.data_qubits[data_qb]
            if which_anc == 'x':
                (anc_err, data_err) = self._get_cnot_action(anc_err,
                        data_err)
            elif which_anc == 'z':
                (data_err, anc_err) = self._get_cnot_action(data_err,
                        anc_err)
            else:
                raise ValueError("which_anc must be 'x' or 'z', but is "
                                  + str(which_anc))

          # Write the results onto the qubits

            self.anc_qubits[anc_qb] = anc_err
            self.data_qubits[data_qb] = data_err

    def _get_cnot_action(self, c, t):  # test written
        """ This function describes the action of the CNOT gates.

        Input
        -----
        c -- errors on control qubit
        t -- errors on target qubit

        Output
        -----
        c -- errors on control qubit
        t -- errors on target qubit
        """

        # X- or y-error on control

        if c[0]:
            t[0] = not t[0]

        # Y- or z-error on target

        if t[1]:
            c[1] = not c[1]

        return (c, t)

    def _anc_exists(self, m, n):
        """ This function checks if an ancilla qubit exist or is a dummy """

        fake_ancillas = [
            m == 0 and n == 0,
            m == self.dist and n == self.dist,
            m == 0 and np.mod(n, 2) == 1,
            m == self.dist and np.mod(n, 2) == 0,
            np.mod(m, 2) == 0 and n == 0,
            np.mod(m, 2) == 1 and n == self.dist,
            ]
        if any(fake_ancillas):
            return False
        else:
            return True

    def make_run(
        self,
        seed,
        n_steps,
        condensed=True,
        ):
        """ This function first reinitializes the system, and the calculates
        a ('measurement') n_step steps. Note that since we return a final
        stabilizer at each step, it corresponds to n_step actual measurements
        which have the same syndromes (up to the given step where the data
        qubits are read out).

        Input
        -----
        seed -- a seed for the random number generator
        n_steps -- the number of steps (in sets of 7 circuit steps)
        condensed -- a flag determining if the output should be in condensed
                     lists or in arrays that resemble the geometry of the
                     surface code

        Output
        ------
        seed -- the seed that was used for the run
        syndromes -- syndromes
        events -- second derivatives of syndromes
        fstabs -- the final stabilizer calculated from data qubit measurements
        err_signal -- the error signal, which is xor(fstabs, first_deriv)
        parities -- the parities of the bitflip errors on the data qubits
                    (combined x- and y-errors)
        """

        # Reinitialize the system

        self._reinitialize(seed)

        # Execute the seven substeps n_step times

        (syndromes, fstabs, parities) = ([], [], [])
        for s in range(n_steps):
            self._do_step_1()
            self._do_step_2()
            self._do_step_3()
            self._do_step_4()
            self._do_step_5()
            self._do_step_6()

          # The final step is a bit tricky because we do both the 7th step and the
          # final measurement simultaneously.

          # FIRST we must do the final measurement, otherwise we add extra errors.

            if condensed:
                (z_fstabs, parity_meas) = \
                    self._calc_final_z_stabs_condensed()
            else:
                (z_fstabs, parity_meas) = self._calc_final_z_stabs()
            fstabs.append(z_fstabs)

          # The final parity is the parity of the bitflips that occurred on the
          # data qubits + the number of bit flips that occur during the
          # measurement of the data qubits ('final measurements').

            parity_clean = self._get_parity_of_bitflips()
            final_parity = parity_clean != parity_meas
            parities.append(final_parity)

          # SECOND we do the step 7

            if condensed:
                syndromes.append(self._do_measure_step_condensed())
            else:
                syndromes.append(self._do_measure_step())

        syndromes = np.array(syndromes)
        fstabs = np.array(fstabs)
        parities = np.array(parities)

        # Finally, we calculate the first and second derivative (events)
        # of the syndromes and the final error signal.

        first_deriv = []
        for s in range(n_steps):
            if s < 1:
                first_deriv.append(syndromes[s])
            else:
                first_deriv.append(np.bitwise_xor(syndromes[s],
                                   syndromes[s - 1]))
        first_deriv = np.array(first_deriv, dtype=bool)

        second_deriv = []
        for s in range(n_steps):
            if s < 2:
                second_deriv.append(syndromes[s])
            else:
                second_deriv.append(np.bitwise_xor(syndromes[s],
                                    syndromes[s - 2]))
        events = np.array(second_deriv, dtype=bool)

        err_signal = []
        if condensed:
            for s in range(n_steps):
                err_signal.append(np.bitwise_xor(fstabs[s],
                                  first_deriv[s][self.z_indcs]))
        else:
            for s in range(n_steps):
                first_deriv_z_only = np.zeros(shape=[self.dist + 1,
                        self.dist + 1], dtype=bool)
                for z_anc in self.z_anc_l:
                    first_deriv_z_only[z_anc] = first_deriv[s][z_anc]
                err_signal.append(np.bitwise_xor(fstabs[s],
                                  first_deriv_z_only))
        err_signal = np.array(err_signal, dtype=bool)

        return (
            seed,
            syndromes,
            events,
            fstabs,
            err_signal,
            parities,
            )

    def get_info(self):
        """ This function returns some information about the variables that
        describe the surface code model.
        """

        return {
            'git_version': self.git_version,
            'seed': self.seed,
            'distance': self.dist,
            'pqx': self.pqx,
            'pqy': self.pqy,
            'pqz': self.pqz,
            'pax': self.pax,
            'pay': self.pay,
            'paz': self.paz,
            'pm': self.pm,
            'n_data_qubits': self.n_data,
            'n_anc_qubits': self.n_anc,
            'n_z_stabs': self.n_z_stab,
            }
