# ES8 Project

# Running simulation

Build and install patched `batman_adv` module.

```sh
cd batman-patch/batman_adv
make
sudo make install
cd ../battpctl
make
```

Note that `batman-patch/battpctl/battpctl` must be in `PATH`.

Start load `batman_adv` and start simulation.

```sh
sudo modprobe batman_adv
sudo python3 emulation.py ...
```

Note that `emulation.py` depends on numpy.

## Dependencies

- `iperf3`
- `battpctl`
- `batman-patch`
- `numpy`
- `batctl`
