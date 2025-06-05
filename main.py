import math
import heapq
from node import Node, Edge



#we will screenshot the screen, then use the get all function
def screenshot():
    screenshot_num = 0
    img = pyautogui.screenshot(f"Screenshot{screenshot_num}.png")
    screenshot_num += 1


def pathfind(graph, start):
    dist = {node: float('inf') for node in graph }
    dist[start] = 0
    pq = [(0, start)]
    pass





def get_all(house_image):
    all_house = []
    for pos in pyautogui.locateAllOnScreen(house_image): #this returns left, top, width, height 
        all_house.append(pos)
    return all_house

def calculate_weight(Node, others):
    distances = []
    for other in others:
        result = math.dist(Node.get_val(), other.get_val())
        


        distances.append(result)
        distances.append(Node.get_val())
        distances.append(other.get_val())
        

    

    return distances 

    #this gets distance but idk what to do with that

values = [(1,1), (2,2),(3,3)]


for value in values:
    value = Node(value)
    
    



a = Node((1,1))
b = Node((2,2))
c = Node((3,3))
d = Node((-1, 10))
print(calculate_weight(a, [b, c, d]))


