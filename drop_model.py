from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable
import random

class State(Enum):
    RECHARGING = auto()
    FLYING_UP = auto()
    UP = auto()
    FLYING_DOWN = auto()
    DOWN = auto()

@dataclass
class DropoutModel:
    # Model parameters
    name: str
    failure_probability: float
    replacement_distribution_sampler: Callable[[], float]
    time_step: float
    fly_up_time: float
    fly_down_time: float
    desired_fly_time: float
    recharging_time: float

    # Model internals
    state: State = State.FLYING_UP
    time_state_enter: float = 0
    sim_time: float = 0
    replacement_delay: float = 0

    # Model outputs
    sched: list[tuple[float, str, State]] = field(default_factory=list) # updates only

    def set_time_init(self, init_time):
        if len(self.sched) != 0 and self.sim_time != 0 and self.time_state_enter != 0:
            raise Exception("Sim time override can only be called once before simulation start and never after")
        self.sim_time = init_time
        self.time_state_enter = init_time
        self.sched.append((self.sim_time, self.name, self.state))

    def change_state(self, new_state):
        self.sched.append((self.sim_time, self.name, new_state))

        self.state = new_state
        self.time_state_enter = self.sim_time

        if self.state == State.DOWN:
            self.replacement_delay = self.replacement_distribution_sampler()

    def step_state_machine(self, time_in_state):
        if self.state == State.RECHARGING:
            if time_in_state >= self.recharging_time:
                self.change_state(State.FLYING_UP)

        elif self.state == State.FLYING_UP:
            if time_in_state >= self.fly_up_time:
                self.change_state(State.UP)

        elif self.state == State.UP:
            if time_in_state >= (self.desired_fly_time - self.fly_up_time - self.fly_down_time):
                self.change_state(State.FLYING_DOWN)
            elif random.random() < self.failure_probability:
                self.change_state(State.DOWN)

        elif self.state == State.FLYING_DOWN:
            if time_in_state >= self.fly_down_time:
                self.change_state(State.RECHARGING)

        elif self.state == State.DOWN:
            if time_in_state >= self.replacement_delay:
                self.change_state(State.FLYING_UP)

    def step(self):
        self.sim_time += self.time_step
        time_in_state = self.sim_time - self.time_state_enter

        self.step_state_machine(time_in_state)

    def stepn(self, n: int):
        for _ in range(n):
            self.step()

    def stepuntil(self, t: float):
        while self.sim_time < t:
            self.step()

    def get(self):
        return self.sched

class MultipleDroneSim:
    sims: list[DropoutModel]

    def __init__(self, 
                 t_start_step: float,
                 failure_probability: float,
                 replacement_distribution_sampler: Callable[[], float],
                 time_step: float,
                 fly_up_time: float,
                 fly_down_time: float,
                 desired_fly_time: float,
                 recharging_time: float,
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
                    failure_probability=failure_probability,
                    replacement_distribution_sampler=replacement_distribution_sampler,
                    time_step=time_step,
                    fly_up_time=fly_up_time,
                    fly_down_time=fly_down_time,
                    desired_fly_time=desired_fly_time,
                    recharging_time=recharging_time,
                    )
            m.set_time_init(t_start)
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

        result.sort()
        return result

#######################
##### Simple test #####
#######################

def main():
    from pprint import pprint
    sims = MultipleDroneSim(
            names = [f"n{i}" for i in range(5)],
            t_start_step = 50,
            failure_probability = 0.001,
            replacement_distribution_sampler = lambda : 100*random.random()+50,
            time_step = 10,
            fly_up_time = 30,
            fly_down_time = 30,
            desired_fly_time = 900,
            recharging_time = 700,
            )

    sims.stepuntil(2000)
    pprint(sims.get())

if __name__ == "__main__":
    # do a lil' smoke test if we run this as main
    main()
