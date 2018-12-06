# -*- coding: utf-8 -*-
"""
Created on Fri Oct 14 10:51:10 2016

@author: mittelberger
"""

import time
import numpy as np
import threading
import contextlib
from nion.swift.model import HardwareSource
from nion.utils import Event
from nion.data import xdata_1_0 as xd
import logging
import queue
import copy
try:
    import _superscan
except ImportError:
    pass

class MultiEELS(object):
    def __init__(self, **kwargs):
        self.spectrum_parameters = [{'index': 0, 'offset_x': 0, 'offset_y': 0, 'exposure_ms': 1, 'frames': 1},
                                    {'index': 1, 'offset_x': 160, 'offset_y': 160, 'exposure_ms': 8, 'frames': 1},
                                    {'index': 2, 'offset_x': 320, 'offset_y': 320, 'exposure_ms': 16, 'frames': 1}]
        self.settings = {'x_shifter': '', 'y_shifter': 'EELS_4DY', 'x_units_per_ev': 1, 'y_units_per_px': 0.00081,
                         'blanker': '', 'x_shift_delay': 0.05, 'y_shift_delay': 0.05, 'focus': '', 'focus_delay': 0,
                         'saturation_value': 12000, 'y_align': True, 'stitch_spectra': False}
        self.on_low_level_parameter_changed = None
        self.stem_controller = None
        self.camera = None
        self.superscan = None
        self.document_controller = None
#        def update_result_data_item(line: np.ndarray, line_index: int):
#            """
#            This function is only a dummy to show how the real function is expected to be built.
#            """
#        self.update_result_data_item = update_result_data_item
        self.zeros = {'x': 0, 'y': 0, 'focus': 0}
        self.acquisition_state_changed_event = Event.Event()
        self.queue = None
        self.process_and_send_data_thread = None
        self.data_item = None

    def add_spectrum(self, parameters=None):
        if parameters is None:
            parameters = self.spectrum_parameters[-1].copy()
        parameters['index'] = len(self.spectrum_parameters)
        self.spectrum_parameters.append(parameters)
        if callable(self.on_low_level_parameter_changed):
            self.on_low_level_parameter_changed('added_spectrum')

    def remove_spectrum(self):
        assert len(self.spectrum_parameters) > 1, 'Number of spectra cannot become smaller than 1.'
        self.spectrum_parameters.pop()
        if callable(self.on_low_level_parameter_changed):
            self.on_low_level_parameter_changed('removed_spectrum')

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
            
    def get_frames(self, index):
        assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined!'.format(index)
        return self.spectrum_parameters[index]['frames']

    def set_frames(self, index, frames):
        assert index < len(self.spectrum_parameters), 'Index {:.0f} > then number of spectra defined. Add a new spectrum before changing its parameters!'.format(index)
        self.spectrum_parameters[index]['frames'] = frames
        if callable(self.on_low_level_parameter_changed):
            self.on_low_level_parameter_changed('spectrum_parameters')

    def shift_x(self, eV):
        if callable(self.settings['x_shifter']):
            self.settings['x_shifter'](self.zeros['x'] + eV*self.settings['x_units_per_ev'])
        else:
            self.stem_controller.SetValAndConfirm(self.settings['x_shifter'],
                                                  self.zeros['x'] + eV*self.settings['x_units_per_ev'], 1.0, 1000)
        time.sleep(self.settings['x_shift_delay'])

    def shift_y(self, px):
        if callable(self.settings['y_shifter']):
            self.settings['y_shifter'](self.zeros['y'] + px*self.settings['y_units_per_px'])
        else:
            self.stem_controller.SetValAndConfirm(self.settings['y_shifter'],
                                                  self.zeros['y'] + px*self.settings['y_units_per_px'], 1.0, 1000)
        time.sleep(self.settings['y_shift_delay'])

    def adjust_focus(self, x_shift_ev):
        pass

    def blank_beam(self, time=None):
        pass

    def unblank_beam(self, time=None):
        pass

    def get_stitch_ranges(self, spectra):
        #result = np.array(())
        crop_ranges = []
        y_range_0 = np.array((self.spectrum_parameters[0]['offset_y'], self.spectrum_parameters[1]['offset_y']-1))
        x_range_target = np.array((0, 0))
        for i in range(1, len(spectra)):
            y_range = y_range_0 + self.spectrum_parameters[i-1]['offset_y']
            #data = np.sum(spectra[i-1].data[y_range[0]:y_range[1]], axis=0)
            calibration = spectra[i-1].dimensional_calibrations[-1].write_dict()
            calibration_next = spectra[i].dimensional_calibrations[-1].write_dict()
            end = np.rint((calibration_next['offset']-calibration['offset'])/calibration['scale']).astype(np.int)
            x_range_source = np.array((0, end))
            x_range_target = np.array((x_range_target[1], x_range_target[1] + x_range_source[1]-x_range_source[0]))
            crop_ranges.append((y_range, x_range_source, x_range_target))
            #result = np.append(result, data[:end])
        #result = np.append(result, np.sum(spectra[-1].data[self.spectrum_parameters[-1]['offset_y']:], axis=0))
        y_range = y_range_0 + self.spectrum_parameters[-1]['offset_y']
        x_range_source = np.array((0, None))
        x_range_target = np.array((x_range_target[1], x_range_target[1] + spectra[-1].data.shape[1]))
        crop_ranges.append((y_range, x_range_source, x_range_target))
        #result = np.array(result)
#        print(crop_ranges)
        return crop_ranges
        #return self.process_spectra(spectra, crop_ranges)

    def stitch_spectra(self, spectra, crop_ranges):
        result = np.zeros(crop_ranges[-1][2][1])
        last_mean = None
        last_overlap = None
        for i in range(len(crop_ranges)):
            data = (spectra[i].data)/self.spectrum_parameters[i]['exposure_ms']
            # check if hdr needs to be done in this interval, which is true when the overlap with the next one is 100%
            if i > 0 and (crop_ranges[i-1][1][1] - crop_ranges[i-1][1][0]) == 0:
                data[data>self.settings['saturation_value']] = (spectra[i-1].data[[data>self.settings['saturation_value']]])/self.spectrum_parameters[i]['exposure_ms']

            data = np.sum(data[crop_ranges[i][0][0]:crop_ranges[i][0][1]], axis=0)
            if last_mean is not None:
                data -= np.mean(data[crop_ranges[i][1][0]:last_overlap]) - last_mean
                print(last_mean, last_overlap)
            if self.settings['y_align'] and i < len(crop_ranges) - 1:
                last_overlap = data.shape[-1] - crop_ranges[i][1][1]
                last_mean = np.mean(data[crop_ranges[i][1][1]:])
            result[crop_ranges[i][2][0]:crop_ranges[i][2][1]] = data[crop_ranges[i][1][0]:crop_ranges[i][1][1]]

        return result

    def acquire_multi_eels(self):
        spectra = []
        if not callable(self.settings['x_shifter']):
            self.zeros['x'] = self.stem_controller.GetVal(self.settings['x_shifter'])
        if not callable(self.settings['y_shifter']):
            self.zeros['y'] = self.stem_controller.GetVal(self.settings['y_shifter'])
        start_frame_parameters = self.camera.get_current_frame_parameters()
        for parameters in self.spectrum_parameters:
            self.shift_x(parameters['offset_x'])
            self.shift_y(parameters['offset_y'])
            self.adjust_focus(parameters['offset_x'])
            frame_parameters = self.camera.get_current_frame_parameters()
            frame_parameters['exposure_ms'] =  parameters['exposure_ms']
            frame_parameters['processing'] = 'sum_processor'
            self.camera.set_current_frame_parameters(frame_parameters)
            self.camera.start_playing()
            self.camera.grab_next_to_start()
            self.camera.grab_sequence_prepare(parameters['frames'])
            xdata = self.camera.grab_sequence(parameters['frames'])[0]
            self.camera.stop_playing()
            if xdata.datum_dimension_count != 1:
                spectra.append(xd.sum(xdata, axis=(0, 1)))
            else:
                spectra.append(xd.sum(xdata, axis=(0)))

        self.camera.set_current_frame_parameters(start_frame_parameters)
        self.shift_y(0)
        self.shift_x(0)
        self.adjust_focus(0)
        if self.settings['stitch_spectra']:
            crop_ranges = self.get_stitch_ranges(spectra)
            return {'data': [self.stitch_spectra(spectra, crop_ranges)], 'stitched_data': True}
        else:
            return {'data': spectra, 'stitched_data': False}

    def process_and_send_data(self):
        while True:
            if self.data_item is None:
                print('data item is none')
                time.sleep(0.05)
                continue
            line_number, images = self.queue.get()
            if images == None:
                break
            if self.data_item.data is None:
                spectra = []
                for k in range(len(images)):
                    di = copy.copy(images[k])
                    di._set_data(di.data[0])
                    spectra.append(di)
                crop_ranges = self.get_stitch_ranges(spectra)
                data = np.zeros((self.number_lines, self.scan_parameters['size'][1], crop_ranges[-1][-1][-1]))
            else:
                data = self.data_item.data
            row = []
            for i in range(images[0].data.shape[0]):
                spectra = []
                for k in range(len(images)):
                    di = copy.copy(images[k])
                    di._set_data(di.data[i])
                    spectra.append(di)
                crop_ranges = self.get_stitch_ranges(spectra)
                row.append(self.stitch_spectra(spectra, crop_ranges))
            row = np.array(row)
            data[line_number] = row
            self.data_item.set_data(data)
            self.queue.task_done()

    def acquire_multi_eels_spectrum_image(self):
        if not callable(self.settings['x_shifter']):
            self.zeros['x'] = self.stem_controller.get_property_as_float(self.settings['x_shifter'])
        if not callable(self.settings['y_shifter']):
            self.zeros['y'] = self.stem_controller.get_property_as_float(self.settings['y_shifter'])
        try:
            logging.debug("start")
            self.acquisition_state_changed_event.fire({"message": "start"})
            eels_camera_parameters = self.camera.get_frame_parameters_for_profile_by_index(2)
            self.scan_parameters = self.superscan.get_frame_parameters_for_profile_by_index(2)
            scan_max_size = 256
            self.scan_parameters["size"] = (min(scan_max_size, self.scan_parameters["size"][0]),
                                            min(scan_max_size, self.scan_parameters["size"][1]))
            self.scan_parameters["pixel_time_us"] = int(1000) #int(1000 * eels_camera_parameters["exposure_ms"] * 0.75)
            self.scan_parameters["external_clock_wait_time_ms"] = int(3000) #int(eels_camera_parameters["exposure_ms"]) + 100
            self.scan_parameters["external_clock_mode"] = 1
            self.scan_parameters["ac_frame_sync"] = False
            self.scan_parameters["ac_line_sync"] = False

            library = self.document_controller.library
            def create_data_item():
                self.data_item = library.create_data_item(title='MutliEELS Spectrum Image')
            self.document_controller.queue_task(create_data_item)

            flyback_pixels = 2
            self.number_lines = self.scan_parameters["size"][0]
            #self.scan_parameters["size"] = (len(self.spectrum_parameters), self.scan_parameters["size"][1])
            self.queue = queue.Queue()
            self.process_and_send_data_thread = threading.Thread(target=self.process_and_send_data)
            self.process_and_send_data_thread.start()
            _superscan.Scan_Settings_Property( _superscan.Scan_Property_Integer(len(self.spectrum_parameters)), _superscan.Scan_Settings_LineRepeat())
            with contextlib.closing(self.superscan.create_view_task(self.scan_parameters)):
#                scan_center_y = self.scan_parameters["fov_nm"]/self.number_lines*(line-self.number_lines/2)
#                self.scan_parameters["center_nm"] = (scan_center_y, self.scan_parameters["center_nm"][1])
                for line in range(self.number_lines):
                    res = self.acquire_multi_eels_line(self.scan_parameters["size"][1], flyback_pixels=flyback_pixels, first_line=line==0)
                    self.queue.put((line, res))
#                    scan_height = scan_parameters["size"][0]
#                    scan_width = scan_parameters["size"][1] + flyback_pixels
#                    data_element = self.camera._hardware_source.acquire_sequence(scan_width * scan_height)
#                    data_shape = data_element["data"].shape
#                    data_element["data"] = data_element["data"].reshape(scan_height, scan_width, data_shape[1])[:, 0:scan_width-flyback_pixels, :]
#                    data_and_metadata = HardwareSource.convert_data_element_to_data_and_metadata(data_element)
#                    def create_and_display_data_item():
#                        data_item = library.create_data_item_from_data_and_metadata(data_and_metadata)
#                        self.document_controller.display_data_item(data_item)
#                    self.document_controller.queue_task(create_and_display_data_item)  # must occur on UI thread
        except Exception as e:
            import traceback
            traceback.print_stack()
            print(e)
            raise
        finally:
            self.acquisition_state_changed_event.fire({"message": "end"})
            _superscan.Scan_Settings_Property(_superscan.Scan_Property_Integer(0), _superscan.Scan_Settings_LineRepeat())
            self.queue.join()
            self.queue.put((None, None))
            self.process_and_send_data_thread.join()
            self.queue = None
            self.process_and_send_data_thread = None
            self.shift_y(0)
            self.shift_x(0)
            self.adjust_focus(0)
            self.superscan.abort_playing()
            logging.debug("end")

    def acquire_multi_eels_line(self, x_pixels, flyback_pixels=2, first_line=False, last_line=False):
        images = []
        for i in range(len(self.spectrum_parameters)):
            self.shift_x(self.spectrum_parameters[i]['offset_x'])
            self.shift_y(self.spectrum_parameters[i]['offset_y'])
            self.adjust_focus(self.spectrum_parameters[i]['offset_x'])
            self.camera.abort_playing()
            self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.mode = 'kinetic series'
            self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.frame_parameters = {'exposure_ms': self.spectrum_parameters[i]['exposure_ms'], 'kinetic_ms': self.spectrum_parameters[i]['exposure_ms']}
            if i == 0:
                if first_line:
                    res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels)
                    images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
                else:
                    res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels + flyback_pixels-1)
                    res['data'] = res['data'][flyback_pixels-1:]
                    images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
            elif False: #i == len(self.spectrum_parameters) - 1:
                res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels + flyback_pixels-1)
                #res['data'] = res['data'][flyback_pixels:-flyback_pixels]
                res['data'] = res['data'][:-(flyback_pixels-1)]
                images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
            else:
                res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels + flyback_pixels)
                #res['data'] = res['data'][flyback_pixels:]
                res['data'] = res['data'][:-flyback_pixels]
                images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
        return images
