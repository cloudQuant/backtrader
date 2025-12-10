import numpy as np
import pandas as pd


def test_to_numpy():
    df = pd.DataFrame([[1, 2, 3], [4, 5, 6]], columns=["a", "b", "c"])
    target_array = np.array([[1, 2, 3], [4, 5, 6]])
    result_array = df.to_numpy()
    np.testing.assert_array_equal(result_array, target_array)


if __name__ == "__main__":
    test_to_numpy()
