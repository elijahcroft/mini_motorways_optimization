import pyautogui
pyautogui.screenshot("screenshot.png")





#the goal is to locate the houses and the stores on the game and use an algo to find optimal path

matches = pyautogui.locateAllOnScreen('/house_images./pink_house.png')
for match in matches:
    print(match)
