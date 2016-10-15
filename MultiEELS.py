# -*- coding: utf-8 -*-
"""
Created on Fri Oct 14 10:51:10 2016

@author: mittelberger
"""

import time
import numpy as np

class MultiEELS(object):
    def __init__(self, **kwargs):
        self.spectrum_parameters = [{'index': 0, 'offset_x': 0, 'offset_y': 0, 'exposure_ms': 0.1},
                                    {'index': 1, 'offset_x': 0, 'offset_y': 100, 'exposure_ms': 10},
                                    {'index': 2, 'offset_x': 100, 'offset_y': 200, 'exposure_ms': 100}]
        self.settings = {'x_shifter': '', 'y_shifter': 'EELS_4DY', 'x_units_per_ev': 1, 'y_units_per_px': 1,
                         'blanker': '', 'x_shift_delay': 0.2, 'y_shift_delay': 0.01, 'focus': '', 'focus_delay': 0}
        self.on_low_level_parameter_changed = None
        self.as2 = None
        self.camera = None
        self.zeros = {'x': 0, 'y': 0, 'focus': 0}
                         
        def add_spectrum(self, parameters=None):
            if parameters is None:
                parameters = self.spectrum_parameters[-1].copy()
            parameters['index'] = len(self.spectrum_parameters)
            self.spectrum_parameters.append(parameters)
            if callable(self.on_low_level_parameter_changed):
                self.on_low_level_parameter_changed('spectrum_parameters')
        
        def remove_spectrum(self):
            assert len(self.spectrum_parameters) > 1, 'Number of spectra cannot become smaller than 1.'
            self.spectrum_parameters.pop()
            if callable(self.on_low_level_parameter_changed):
                self.on_low_level_parameter_changed('spectrum_parameters')

        def get_offset_x(self, index):
            assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined!'.format(index)
            return self.spectrum_parameters[index]['offset_x']
            
        def set_offset_x(self, index, offset_x):
            assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined. Add a new spectrum before changing its parameters!'.format(index)
            self.spectrum_parameters[index]['offset_x'] = offset_x
            if callable(self.on_low_level_parameter_changed):
                self.on_low_level_parameter_changed('spectrum_parameters')

        def get_offset_y(self, index):
            assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined!'.format(index)
            return self.spectrum_parameters[index]['offset_y']

        def set_offset_y(self, index, offset_y):
            assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined. Add a new spectrum before changing its parameters!'.format(index)
            self.spectrum_parameters[index]['offset_y'] = offset_y
            if callable(self.on_low_level_parameter_changed):
                self.on_low_level_parameter_changed('spectrum_parameters')
            
        def get_exposure_ms(self, index):
            assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined!'.format(index)
            return self.spectrum_parameters[index]['exposure_ms']

        def set_exposure_ms(self, index, exposure_ms):
            assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined. Add a new spectrum before changing its parameters!'.format(index)
            self.spectrum_parameters[index]['exposure_ms'] = exposure_ms
            if callable(self.on_low_level_parameter_changed):
                self.on_low_level_parameter_changed('spectrum_parameters')
                
        def shift_x(self, eV):
            if callable(self.settings['x_shifter']):
                self.settings['x_shifter'](self.zeros['x'] + eV*self.settings['x_units_per_ev'])
            else:
                self.as2.set_property_as_float(self.settings['x_shifter'],
                                               self.zeros['x'] + eV*self.settings['x_units_per_ev'])
            
            time.sleep(self.settings['x_shift_delay'])
        
        def shift_y(self, px):
            if callable(self.settings['y_shifter']):
                self.settings['y_shifter'](self.zeros['y'] + px*self.settings['y_units_per_ev'])
            else:
                self.as2.set_property_as_float(self.settings['y_shifter'],
                                               self.zeros['y'] + px*self.settings['y_units_per_ev'])
            
            time.sleep(self.settings['y_shift_delay'])
        
        def adjust_focus(self, x_shift_ev):
            pass
        
        def blank_beam(self, time=None):
            pass
        
        def unblank_beam(self, time=None):
            pass

        def stitch_spectra(self, spectra):
            result = []
            for i in range(1, len(spectra)):
                y_range = (self.spectrum_parameters[i-1]['y_shift_px'], self.spectrum_parameters[i]['y_shift_px']-1)
                data = np.sum(spectra[i-1].data[y_range[0]:y_range[1]], axis=0)
                calibration = spectra[i-1].metadata['hardware_source']['spatial_calibrations'][1]
                calibration_next = spectra[i].metadata['hardware_source']['spatial_calibrations'][1]
                end = np.rint((calibration_next['offset']-calibration['offset'])/calibration['scale']).astype(np.int)
                result.append(data[:end])
            result.append(np.sum(spectra[-1].data[self.spectrum_parameters[-1]['y_shift_px']:], axis=0))
            result = np.array(result)
            
            return result.ravel()
        
        def acquire_multi_eels(self):
            spectra = []
            if not callable(self.settings['x_shifter']):
                self.zeros['x'] = self.as2.get_property_as_float(self.settings['x_shifter'])
            if not callable(self.settings['y_shifter']):
                self.zeros['y'] = self.as2.get_property_as_float(self.settings['y_shifter'])
                
            for parameters in self.spectrum_parameters:
                self.shift_x(parameters['x_shift_ev'])
                self.shift_y(parameters['y_shift_px'])
                self.adjust_focus(parameters['x_shift_ev'])
                frame_parameters = {'exposure_ms': parameters['exposure_ms']}
                spectra.append(self.camera.record(frame_parameters)[0])
            self.shift_x(0)
            self.shift_y(0)
            self.adjust_focus(0)
            calibration = spectra[0].metadata['hardware_source']['spatial_calibrations'][1]
            return {'data': self.stitch_spectra(spectra), 'properties': {'spatial_calibrations': [calibration]}}