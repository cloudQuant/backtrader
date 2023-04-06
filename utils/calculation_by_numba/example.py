@njit
def add_arrays(a, b):
    result = np.zeros(a.shape[0], dtype=np.int32)
    for i in range(a.shape[0]):
        result[i] = a[i] + b[i]
    return result

cc = CC('mylib')
cc.export('add_arrays', 'int32[:](int32[:], int32[:])')(add_arrays)
cc.compile()