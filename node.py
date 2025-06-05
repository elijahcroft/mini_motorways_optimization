
class Node:
    def __init__(self, val):
        self.value = val
        self.neighbor = []
        self.weight = 0
        self.color = ''
    def set_val(self, val):
        self.value = val
    def get_val(self):
        return self.value
    def set_weight(self, val):
        self.weight = val
    def get_weight(self):
        return self.weight
    def set_color(self, value):
        self.color = value
    def get_color(self):
        return self.color

class Edge:
    def __init__(self, cur, next):
        self.color = ''
        self.weight = 0
    def set_color(self, value):
        self.color = value
    def get_color(self):
        return self.color
    def get_weight(self):
        return self.weight
    def set_weight(self, val):
        self.weight = val
    



