# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.
import concurrent.futures
import json
from json import *
def print_hi(name):
    # Use a breakpoint in the code line below to debug your script.
    print(f'Hi, {name}')  # Press Ctrl+F8 to toggle the breakpoint.


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    print(str({f"name": "mk"}))
    s = json.dumps({f"name": "mk"})
    with concurrent.futures.ThreadPoolExecutor as excutor:
        excutor.map()
    print(isinstance(json.loads(s), dict))

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
