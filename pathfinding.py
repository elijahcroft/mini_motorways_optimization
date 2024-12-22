import pyautogui
from PIL import Image
import cv2
import math


pyautogui.screenshot("screenshot.png")


target_house = '/house_images/pink_house.png'
target_store = '/store_images/store_icon.png'


houses = list(pyautogui.locateAllOnScreen(target_house, confidence=0.8))
stores = list(pyautogui.locateAllOnScreen(target_store, confidence=0.8))


if houses:
    print(f"Found {len(houses)} houses:")
    for house in houses:
        print(f"House at: {house}")
else:
    print("No houses found.")

if stores:
    print(f"Found {len(stores)} stores:")
    for store in stores:
        print(f"Store at: {store}")
else:
    print("No stores found.")


def euclidean_distance(point1, point2):
    return math.sqrt((point1[0] - point2[0])**2 + (point1[1] - point2[1])**2)

graph = {}
for house in houses:
    house_center = (house.left + house.width // 2, house.top + house.height // 2)
    graph[house_center] = []
    for store in stores:
        store_center = (store.left + store.width // 2, store.top + store.height // 2)
        distance = euclidean_distance(house_center, store_center)
        graph[house_center].append((store_center, distance))

print("Graph of distances:")
for node, edges in graph.items():
    print(f"{node} -> {edges}")

