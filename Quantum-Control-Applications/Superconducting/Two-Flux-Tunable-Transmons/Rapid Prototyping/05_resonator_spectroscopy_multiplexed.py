from qm.QuantumMachinesManager import QuantumMachinesManager
from qm.simulate import LoopbackInterface
from qm import SimulationConfig
from qm.qua import *
import matplotlib.pyplot as plt
from qualang_tools.loops import from_array
from qualang_tools.results import fetching_tool
from quam import QuAM
from configuration import build_config, u

#########################################
# Set-up the machine and get the config #
#########################################
machine = QuAM("quam_bootstrap_state.json", flat_data=False)
config = build_config(machine)

###################
# The QUA program #
###################
dfs = np.arange(-12e6, +12e6, 0.1e6)
n_avg = 1000
depletion_time = 1000

res_if_1 = machine.resonators[0].f_res - machine.local_oscillators.readout[0].freq
res_if_2 = machine.resonators[1].f_res - machine.local_oscillators.readout[0].freq

with program() as multi_res_spec:
    I = [declare(fixed) for _ in range(2)]
    Q = [declare(fixed) for _ in range(2)]
    I_st = [declare_stream() for _ in range(2)]
    Q_st = [declare_stream() for _ in range(2)]
    n = declare(int)
    df = declare(int)

    with for_(n, 0, n < n_avg, n + 1):
        with for_(*from_array(df, dfs)):
            # wait for the resonators to relax
            wait(depletion_time * u.ns, "rr0", "rr1")

            # resonator 1
            update_frequency("rr0", df + res_if_1)
            measure(
                "readout",
                "rr0",
                None,
                dual_demod.full("cos", "out1", "sin", "out2", I[0]),
                dual_demod.full("minus_sin", "out1", "cos", "out2", Q[0]),
            )
            save(I[0], I_st[0])
            save(Q[0], Q_st[0])

            # align("rr1", "rr1")  # Uncomment to measure sequentially
            # resonator 2
            update_frequency("rr1", df + res_if_2)
            measure(
                "readout",
                "rr1",
                None,
                dual_demod.full("cos", "out1", "sin", "out2", I[1]),
                dual_demod.full("minus_sin", "out1", "cos", "out2", Q[1]),
            )
            save(I[1], I_st[1])
            save(Q[1], Q_st[1])

    with stream_processing():
        # resonator 1
        I_st[0].buffer(len(dfs)).average().save("I1")
        Q_st[0].buffer(len(dfs)).average().save("Q1")

        # resonator 2
        I_st[1].buffer(len(dfs)).average().save("I2")
        Q_st[1].buffer(len(dfs)).average().save("Q2")

#####################################
#  Open Communication with the QOP  #
#####################################
qmm = QuantumMachinesManager(machine.network.qop_ip, machine.network.qop_port)

simulate = False
if simulate:
    # simulate the test_config QUA program
    job = qmm.simulate(
        config,
        multi_res_spec,
        SimulationConfig(
            11000, simulation_interface=LoopbackInterface([("con1", 1, "con1", 1), ("con1", 2, "con1", 2)], latency=250)
        ),
    )
    job.get_simulated_samples().con1.plot()

else:
    # Open a quantum machine to execute the QUA program
    qm = qmm.open_qm(config)
    # Execute the QUA program
    job = qm.execute(multi_res_spec)
    # Tool to easily fetch results from the OPX (results_handle used in it)
    results = fetching_tool(job, ["I1", "Q1", "I2", "Q2"])
    # Fetch results
    I1, Q1, I2, Q2 = results.fetch_all()
    # Data analysis
    s1 = u.demod2volts(I1 + 1j * Q1, machine.resonators[0].readout_pulse_length)
    s2 = u.demod2volts(I2 + 1j * Q2, machine.resonators[0].readout_pulse_length)
    # Plot
    fig, ax = plt.subplots(1, 2)
    ax[0].plot(machine.resonators[0].f_res / u.MHz + dfs / u.MHz, np.abs(s1))
    ax[0].set_title("resonator 1")
    ax[0].set_ylabel("Amp (V)")
    ax[0].set_xlabel("Freq (MHz)")
    ax[1].plot(machine.resonators[1].f_res / u.MHz + dfs / u.MHz, np.abs(s2))
    ax[1].set_title("resonator 2")
    ax[1].set_xlabel("Freq (MHz)")
    plt.tight_layout()
    # Close the quantum machines at the end in order to put all flux biases to 0 so that the fridge doesn't heat-up
    qm.close()
try:
    from qualang_tools.plot.fitting import Fit

    fit = Fit()
    plt.figure()
    plt.subplot(121)
    res_1 = fit.reflection_resonator_spectroscopy((machine.resonators[0].f_res + dfs) / u.MHz, np.abs(s1), plot=True)
    plt.xlabel("rr1 IF (MHz)")
    machine.resonators[0].f_res = res_1["f"] * u.MHz
    machine.resonators[0].f_opt = machine.resonators[0].f_res
    plt.subplot(122)
    res_2 = fit.reflection_resonator_spectroscopy((machine.resonators[1].f_res + dfs) / u.MHz, np.abs(s2), plot=True)
    plt.xlabel("rr21 IF (MHz)")
    machine.resonators[1].f_res = res_2["f"] * u.MHz
    machine.resonators[1].f_opt = machine.resonators[1].f_res
except (Exception,):
    pass

# machine._save("quam_bootstrap_state.json")