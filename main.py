import math
import heapq
from node import Node, Edge
import matplotlib.pyplot as plt
import numpy as np
import random


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



def calculate_weight(Node, other): #overload no list
    distances = []
    
    result = math.dist(Node.get_val(), other.get_val())
    distances.append(result)
    distances.append(Node.get_val())
    distances.append(other.get_val())

    return distances 

    #this gets distance but idk what to do with that

def calculate_weights(Node, others):
    distances = []
    for other in others:
        result = math.dist(Node.get_val(), other.get_val())
        distances.append(result)
        distances.append(Node.get_val())
        distances.append(other.get_val())

    return distances 

    #this gets distance but idk what to do with that
def draw_edge(Node, other):
    if(Node.get_color() == other.get_color()):
        edge = Edge(Node, other)
        edge.set_color(Node.get_color())
        edge.set_weight(calculate_weight(Node, other))
        return edge
    else:
        pass





a = Node((1,1))
b = Node((2,2))
c = Node((3,3))
d = Node((-1, 10))
e = Node((2,10))
a.set_color("red")
b.set_color("red")
c.set_color("blue")
d.set_color("blue")
nodes = [a,b,c,d,e]



#generates random data
for _ in range(100):
    _ = Node((random.randint(-100,100), random.randint(-100,100)))
    nodes.append(_)


nodes_plot = []
for i in range(len(nodes)):
    for _ in range(len(nodes)):
        if(nodes[i-1].get_color() == nodes[i].get_color() and nodes[i].get_color() != ''):
            edge = draw_edge(nodes[i-1], nodes[i])
            nodes_plot.append(edge.get_weight())

node_x = []
node_y = []
for node in nodes:
    node_x.append(node.get_val()[0])
    node_y.append(node.get_val()[1])
    
#plots the random data, eventually it will not
fig, ax = plt.subplots(figsize=(5, 2.7))
ax.scatter(node_x, node_y, s=50, facecolor='C1', edgecolor='k', )
plt.show()