新的源代码修改，引入了两个新的测试用例的失败，尝试修复源代码，使得这两个测试用例能通过，同时又不会导致其他的测试用例失败：

FAILED tests/add_tests/test_functions.py::test_functions_max_min - assert nan >= nan
FAILED tests/add_tests/test_ind_psar.py::test_run - AssertionError: 

         - tests/add_tests/test_functions.py:92 test_functions_max_min
         - tests/add_tests/test_ind_psar.py:20 test_run