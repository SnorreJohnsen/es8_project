from enum import Enum
from typing import Callable
import random
from pydantic import BaseModel

class State(str, Enum):
    RECHARGING = "RECHARGING"
    FLYING_UP = "FLYING_UP"
    UP = "UP"
    FLYING_DOWN = "FLYING_DOWN"
    DOWN = "DOWN"

class DropoutEvent(BaseModel):
    name: str
    state: State

class DropoutParams(BaseModel):
    failure_probability: float
    replacement_distribution_sampler: Callable[[], float]
    time_step: float
    fly_up_time: float
    fly_down_time: float
    desired_fly_time: float
    recharging_time: float

class DropoutUpDownOnlyParams(BaseModel):
    failure_probability: float
    replacement_delay: float
    time_step: float

class DropoutModel:
    # Model parameters
    name: str
    params: DropoutParams

    # Model outputs
    _sched: list[tuple[float, DropoutEvent]] # updates only

    # Model internals
    _state: State = State.FLYING_UP
    _time_state_enter: float = 0
    _sim_time: float = 0
    _replacement_delay: float = 0

    def __init__(self, name: str, params: DropoutParams, init_time: float = 0) -> None:
        self.name = name
        self.params = params
        self._sim_time = init_time
        self._time_state_enter = init_time
        self._sched = [(self._sim_time, DropoutEvent(name=self.name, state=self._state))]

    def change_state(self, new_state):
        self._sched.append((self._sim_time, DropoutEvent(name=self.name, state=new_state)))

        self._state = new_state
        self._time_state_enter = self._sim_time

        if self._state == State.DOWN:
            self._replacement_delay = self.params.replacement_distribution_sampler()

    def step_state_machine(self, time_in_state):
        if self._state == State.RECHARGING:
            if time_in_state >= self.params.recharging_time:
                self.change_state(State.FLYING_UP)

        elif self._state == State.FLYING_UP:
            if time_in_state >= self.params.fly_up_time:
                self.change_state(State.UP)

        elif self._state == State.UP:
            if time_in_state >= (self.params.desired_fly_time - self.params.fly_up_time - self.params.fly_down_time):
                self.change_state(State.FLYING_DOWN)
            elif random.random() < self.params.failure_probability:
                self.change_state(State.DOWN)

        elif self._state == State.FLYING_DOWN:
            if time_in_state >= self.params.fly_down_time:
                self.change_state(State.RECHARGING)

        elif self._state == State.DOWN:
            if time_in_state >= self._replacement_delay:
                self.change_state(State.FLYING_UP)

    def step(self):
        self._sim_time += self.params.time_step
        time_in_state = self._sim_time - self._time_state_enter

        self.step_state_machine(time_in_state)

    def stepn(self, n: int):
        for _ in range(n):
            self.step()

    def stepuntil(self, t: float):
        while self._sim_time < t:
            self.step()

    def get(self):
        return self._sched

class DropoutUpDownOnlyModel:
    # Model parameters
    name: str
    params: DropoutUpDownOnlyParams

    # Model outputs
    _sched: list[tuple[float, DropoutEvent]] # updates only

    # Model internals
    _state: State = State.UP
    _time_state_enter: float = 0
    _sim_time: float = 0
    _replacement_delay: float = 0

    def __init__(self, name: str, params: DropoutUpDownOnlyParams, init_time: float = 0) -> None:
        self.name = name
        self.params = params
        self._sim_time = init_time
        self._time_state_enter = init_time
        self._sched = []

    def change_state(self, new_state):
        self._sched.append((self._sim_time, DropoutEvent(name=self.name, state=new_state)))

        self._state = new_state
        self._time_state_enter = self._sim_time

        if self._state == State.DOWN:
            self._replacement_delay = self.params.replacement_delay

    def step_state_machine(self, time_in_state):
        if self._state == State.UP:
            sample = random.random()
            if sample < self.params.failure_probability:
                self.change_state(State.DOWN)
        elif self._state == State.DOWN:
            if time_in_state >= self._replacement_delay:
                self.change_state(State.UP)
        else:
            raise ValueError(f"Simple Dropout Model reached invalid state {self._state}")

    def step(self):
        self._sim_time += self.params.time_step
        time_in_state = self._sim_time - self._time_state_enter

        self.step_state_machine(time_in_state)

    def stepn(self, n: int):
        for _ in range(n):
            self.step()

    def stepuntil(self, t: float):
        while self._sim_time < t:
            self.step()

    def get(self):
        return self._sched

class MultipleDroneSim:
    sims: list[DropoutModel]

    def __init__(self, 
                 t_start_step: float,
                 params: DropoutParams,
                 n: int | None = None, 
                 names: list[str] | None = None
                 ):
        if n:
            if names:
                assert len(names) == n
            else:
                names = [f"dropout_sim{i}" for i in range(n)]
        else:
            assert names is not None
            n = len(names)

        t_start_ar = []
        for i in range(n):
            t_start_ar.append(i*t_start_step)

        random.shuffle(t_start_ar) # randomize start delay order

        sims = []
        for name, t_start in zip(names, t_start_ar):
            m = DropoutModel(
                    name = name,
                    params = params,
                    init_time = t_start,
                    )
            sims.append(m)

        self.sims = sims

    def step(self):
        for m in self.sims:
            m.step()

    def stepn(self, n: int):
        for _ in range(n):
            self.step()

    def stepuntil(self, t: float):
        for m in self.sims:
            m.stepuntil(t)

    def get(self):
        result = []
        for m in self.sims:
            result.extend(m.get())
        return result

class SimpleDroneSim: # UP/DOWN (fail-only) simulation over multiple drones
    sims: list[DropoutUpDownOnlyModel]

    def __init__(self, 
                 params: DropoutUpDownOnlyParams,
                 n: int | None = None, 
                 names: list[str] | None = None
                 ):
        if n:
            if names:
                assert len(names) == n
            else:
                names = [f"dropout_sim{i}" for i in range(n)]
        else:
            assert names is not None
            n = len(names)

        sims = []
        for name in names:
            m = DropoutUpDownOnlyModel(
                    name = name,
                    params = params,
                    )
            sims.append(m)

        self.sims = sims

    def step(self):
        for m in self.sims:
            m.step()

    def stepn(self, n: int):
        for _ in range(n):
            self.step()

    def stepuntil(self, t: float):
        for m in self.sims:
            m.stepuntil(t)

    def get(self):
        result = []
        for m in self.sims:
            result.extend(m.get())
        return result
#######################
##### Simple test #####
#######################

def main():
    params = DropoutParams(
                    failure_probability = 0.001,
                    replacement_distribution_sampler = lambda : 100*random.random()+50,
                    time_step = 10,
                    fly_up_time = 30,
                    fly_down_time = 30,
                    desired_fly_time = 900,
                    recharging_time = 700,
            )
    sims = MultipleDroneSim(
            names = [f"n{i}" for i in range(5)],
            t_start_step = 50,
            params = params, 
            )

    sims.stepuntil(2000)
    from pprint import pprint
    pprint(sims.get())

    params = DropoutUpDownOnlyParams(
            failure_probability=0.05,
            replacement_delay=30,
            time_step=10,
            )
    sim = SimpleDroneSim(
            names = [f"n{i}" for i in range(5)],
            params = params, 
            )
    sim.stepuntil(500)
    print("======= Simple UP/DOWN only ========")
    pprint(sim.get())

if __name__ == "__main__":
    # do a lil' smoke test if we run this as main
    main()
