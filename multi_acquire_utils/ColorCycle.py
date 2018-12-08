# -*- coding: utf-8 -*-
"""
Created on Thu Dec  6 11:26:12 2018

@author: Andreas
"""
import itertools

# copied from https://github.com/mrmrs/colors
color_names = {
    'aqua':    '#7fdbff',
    'blue':    '#0074d9',
    'lime':    '#01ff70',
    'navy':    '#001f3f',
    'teal':    '#39cccc',
    'olive':   '#3d9970',
    'green':   '#2ecc40',
    'red':     '#ff4136',
    'maroon':  '#85144b',
    'orange':  '#ff851b',
    'purple':  '#b10dc9',
    'yellow':  '#ffdc00',
    'fuchsia': '#f012be',
    'gray':    '#aaaaaa',
    'white':   '#ffffff',
    'black':   '#111111',
    'silver':  '#dddddd'
}

color_order = ['blue',
               'red', 
               'green',
               'navy',
               'aqua',
               'yellow',
               'gray',
               'black',
               'orange',
               'maroon',
               'purple',
               'teal',
               'olive',
               'lime',
               'fuchsia',
               'silver']

_color_cycle = itertools.cycle(color_order)

def get_next_color():
    color = next(_color_cycle)
    return color_names[color]

def reset_color_cycle():
    global _color_cycle
    _color_cycle = itertools.cycle(color_order)