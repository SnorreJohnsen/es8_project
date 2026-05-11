
def report(t):
    print(f"seconds={t}")
    print(f"minutes={t/60}")
    print(f"hours={t/3600}")
    print(f"days={t/(3600*24)}")

def simtime(fixed=60, silence=30, streamlen=10, delay=10, stream_seq=[1, 2, 4, 6, 8, 10, 15, 20, 25, 30, 40]):
    return len(stream_seq)*(silence+streamlen) + fixed + delay

def runtime(simtime, num_loss=1, num_mesh=4, bitrates=["100k", "500k", "1M", "2M", "5M"], num_iters=10):
    runs = num_loss * num_mesh * len(bitrates) * num_iters
    return simtime * runs
