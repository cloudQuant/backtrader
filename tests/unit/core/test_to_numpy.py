"""Test module for pandas DataFrame to_numpy() method.

This module contains basic tests to verify that the pandas DataFrame.to_numpy()
method correctly converts DataFrame objects to numpy arrays. It serves as a
reference test for understanding numpy array conversion patterns in the
backtrader testing framework.

Example:
    Run this test directly:
        python tests/base_functions/test_to_numpy.py

    Or run via pytest:
        pytest tests/base_functions/test_to_numpy.py -v
"""


import numpy as np
import pandas as pd


def test_to_numpy():
    """Test that DataFrame.to_numpy() correctly converts a DataFrame to a numpy array.

    This test verifies that:
    1. A pandas DataFrame can be converted to a numpy array using to_numpy()
    2. The resulting array contains the same data in the same structure
    3. Column names are dropped during conversion (only values remain)

    Args:
        None

    Returns:
        None

    Raises:
        AssertionError: If the resulting numpy array does not match the
            expected target array.

    Example:
        >>> test_to_numpy()  # No return value, raises AssertionError if test fails
    """
    df = pd.DataFrame([[1, 2, 3], [4, 5, 6]], columns=["a", "b", "c"])
    target_array = np.array([[1, 2, 3], [4, 5, 6]])
    result_array = df.to_numpy()
    np.testing.assert_array_equal(result_array, target_array)


if __name__ == "__main__":
    test_to_numpy()
