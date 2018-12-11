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
from nion.data import DataAndMetadata
from nion.data import Calibration
from nion.instrumentation.scan_base import RecordTask
import logging
import queue
import copy
try:
    import _superscan
except ImportError as e:
    _has_superscan = False
    logging.warn('Could not import _superscan (Reason: {})'.format(str(e)))
else:
    _has_superscan = True

class MultiEELS(object):
    def __init__(self, **kwargs):
        self.spectrum_parameters = [{'index': 0, 'offset_x': 0, 'offset_y': 0, 'exposure_ms': 1, 'frames': 1},
                                    {'index': 1, 'offset_x': 160, 'offset_y': 160, 'exposure_ms': 8, 'frames': 1},
                                    {'index': 2, 'offset_x': 320, 'offset_y': 320, 'exposure_ms': 16, 'frames': 1}]
        self.settings = {'x_shifter': 'EELS_MagneticShift_Offset', 'y_shifter': '', 'x_units_per_ev': 1,
                         'y_units_per_px': 0.00081, 'blanker': '', 'x_shift_delay': 0.05, 'y_shift_delay': 0.05,
                         'focus': '', 'focus_delay': 0, 'saturation_value': 12000, 'y_align': True,
                         'stitch_spectra': False, 'auto_dark_subtract': False, 'bin_spectra': True,
                         'blanker_delay': 0.05}
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
        self.scan_calibrations = [{'offset': 0, 'scale': 1, 'units': ''}, {'offset': 0, 'scale': 1, 'units': ''}]
        self.acquisition_state_changed_event = Event.Event()
        self.new_data_ready_event = Event.Event()
        self.__stop_processing_event = threading.Event()
        self.queue = None
        self.process_and_send_data_thread = None
        self.data_item = None
        self.__active_settings = self.settings
        self.__active_spectrum_parameters = self.spectrum_parameters
        self.abort_event = threading.Event()

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
        if callable(self.__active_settings['x_shifter']):
            self.__active_settings['x_shifter'](self.zeros['x'] + eV*self.__active_settings['x_units_per_ev'])
        elif self.__active_settings['x_shifter']:
            self.stem_controller.SetValAndConfirm(self.__active_settings['x_shifter'],
                                                  self.zeros['x'] + eV*self.__active_settings['x_units_per_ev'], 1.0, 1000)
        time.sleep(self.__active_settings['x_shift_delay'])

    def shift_y(self, px):
        if callable(self.__active_settings['y_shifter']):
            self.__active_settings['y_shifter'](self.zeros['y'] + px*self.__active_settings['y_units_per_px'])
        elif self.__active_settings['y_shifter']:
            self.stem_controller.SetValAndConfirm(self.__active_settings['y_shifter'],
                                                  self.zeros['y'] + px*self.__active_settings['y_units_per_px'], 1.0, 1000)
        time.sleep(self.__active_settings['y_shift_delay'])

    def adjust_focus(self, x_shift_ev):
        pass

    def blank_beam(self):
        self.__set_beam_blanker(True)

    def unblank_beam(self):
        self.__set_beam_blanker(False)

    def __set_beam_blanker(self, blanker_on):
        if callable(self.__active_settings['blanker']):
            self.__active_settings['blanker'](blanker_on)
        elif self.__active_settings['blanker']:
            self.stem_controller.SetValAndConfirm(self.__active_settings['blanker'], 1 if blanker_on else 0, 1.0, 1000)
        time.sleep(self.__active_settings['blanker_delay'])

    def get_stitch_ranges(self, spectra):
        #result = np.array(())
        crop_ranges = []
        y_range_0 = np.array((self.__active_spectrum_parameters[0]['offset_y'], self.__active_spectrum_parameters[1]['offset_y']-1))
        x_range_target = np.array((0, 0))
        for i in range(1, len(spectra)):
            y_range = y_range_0 + self.__active_spectrum_parameters[i-1]['offset_y']
            #data = np.sum(spectra[i-1].data[y_range[0]:y_range[1]], axis=0)
            calibration = spectra[i-1].dimensional_calibrations[-1].write_dict()
            calibration_next = spectra[i].dimensional_calibrations[-1].write_dict()
            end = np.rint((calibration_next['offset']-calibration['offset'])/calibration['scale']).astype(np.int)
            x_range_source = np.array((0, end))
            x_range_target = np.array((x_range_target[1], x_range_target[1] + x_range_source[1]-x_range_source[0]))
            crop_ranges.append((y_range, x_range_source, x_range_target))
            #result = np.append(result, data[:end])
        #result = np.append(result, np.sum(spectra[-1].data[self.spectrum_parameters[-1]['offset_y']:], axis=0))
        y_range = y_range_0 + self.__active_spectrum_parameters[-1]['offset_y']
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
            data = (spectra[i].data)/self.__active_spectrum_parameters[i]['exposure_ms']
            # check if hdr needs to be done in this interval, which is true when the overlap with the next one is 100%
            if i > 0 and (crop_ranges[i-1][1][1] - crop_ranges[i-1][1][0]) == 0:
                data[data>self.__active_settings['saturation_value']] = (spectra[i-1].data[[data>self.__active_settings['saturation_value']]])/self.__active_spectrum_parameters[i]['exposure_ms']

            data = np.sum(data[crop_ranges[i][0][0]:crop_ranges[i][0][1]], axis=0)
            if last_mean is not None:
                data -= np.mean(data[crop_ranges[i][1][0]:last_overlap]) - last_mean
                print(last_mean, last_overlap)
            if self.__active_settings['y_align'] and i < len(crop_ranges) - 1:
                last_overlap = data.shape[-1] - crop_ranges[i][1][1]
                last_mean = np.mean(data[crop_ranges[i][1][1]:])
            result[crop_ranges[i][2][0]:crop_ranges[i][2][1]] = data[crop_ranges[i][1][0]:crop_ranges[i][1][1]]

        return result

    def __acquire_multi_eels_data(self, number_pixels):
        spectra = []
        parameters_list = []
        for parameters in self.__active_spectrum_parameters:
            if self.abort_event.is_set():
                break
            self.shift_x(parameters['offset_x'])
            self.shift_y(parameters['offset_y'])
            self.adjust_focus(parameters['offset_x'])
            frame_parameters = self.camera.get_current_frame_parameters()
            frame_parameters['exposure_ms'] =  parameters['exposure_ms']
            frame_parameters['processing'] = 'sum_processor' if self.__active_settings['bin_spectra'] else None
            self.camera.set_current_frame_parameters(frame_parameters)
            #self.camera.start_playing()
            #self.camera.grab_next_to_start()
            self.camera.grab_sequence_prepare(parameters['frames']*number_pixels)
            print('start sequence')
            success = False
            while not success:
                try:
                    xdata = self.camera.grab_sequence(parameters['frames']*number_pixels)[0]
                except Exception as e:
                    if str(e) == 'No simulator thread.':
                        success = False
                    else:
                        raise
                else:
                    success = True
            print('end sequence')
            starttime = time.time()
            if self.__active_settings['bin_spectra'] and xdata.datum_dimension_count != 1:
                    xdata = xd.sum(xdata, axis=1)

            # bring data to universal shape: ('pixels', 'frames', 'data', 'data')
            xdata = xd.reshape(xdata, (number_pixels, -1) + (xdata.data_shape[1:]))
            # sum along frames axis
            xdata = xd.sum(xdata, axis=1)
            # create correct data descriptors
            data_descriptor = DataAndMetadata.DataDescriptor(False, 1,
                                                             1 if self.__active_settings['bin_spectra'] else 2)
            xdata._set_data_descriptor(data_descriptor)
            spectra.append(xdata)

            end_ev = parameters['offset_x'] + (spectra[-1].dimensional_calibrations[-1].scale *
                                               spectra[-1].data_shape[-1])
            parms = {'index': parameters['index'],
                     'exposure_ms': parameters['exposure_ms'],
                     'frames': parameters['frames'],
                     'start_ev': parameters['offset_x'],
                     'end_ev': end_ev}
            parameters_list.append(parms)
            print('finished acquisition ({:g} s)'.format(time.time() - starttime))
        return {'data': spectra, 'parameters': parameters_list}

    def acquire_multi_eels_spectrum(self):
        self.__active_settings = copy.deepcopy(self.settings)
        self.__active_spectrum_parameters = copy.copy(self.spectrum_parameters)
        self.abort_event.clear()
        if not callable(self.__active_settings['x_shifter']) and self.__active_settings['x_shifter']:
            self.zeros['x'] = self.stem_controller.GetVal(self.__active_settings['x_shifter'])
        if not callable(self.__active_settings['y_shifter']) and self.__active_settings['y_shifter']:
            self.zeros['y'] = self.stem_controller.GetVal(self.__active_settings['y_shifter'])
        start_frame_parameters = self.camera.get_current_frame_parameters()
        multi_eels_data = self.__acquire_multi_eels_data(1)
        if self.__active_settings['auto_dark_subtract']:
            self.blank_beam()
            dark_data = self.__acquire_multi_eels_data(1)
            for i in range(len(multi_eels_data['data'])):
                multi_eels_data['data'][i] = multi_eels_data['data'][i] - dark_data['data'][i]
            self.unblank_beam()
        self.camera.set_current_frame_parameters(start_frame_parameters)
        self.shift_y(0)
        self.shift_x(0)
        self.adjust_focus(0)
        if self.__active_settings['stitch_spectra']:
            crop_ranges = self.get_stitch_ranges(multi_eels_data['data'])
            return {'data': [self.stitch_spectra(multi_eels_data['data'], crop_ranges)],
                    'stitched_data': True,
                    'parameters': multi_eels_data['parameters']}
        else:
            multi_eels_data['stitched_data'] = False
            data_list = multi_eels_data['data']
            for i in range(len(data_list)):
                data_list[i] = xd.squeeze(data_list[i])
            multi_eels_data['data'] = data_list
            return multi_eels_data

    def acquire_multi_eels_line(self, x_pixels, flyback_pixels=2, first_line=False, last_line=False):
        data_dict = self.__acquire_multi_eels_data(x_pixels+flyback_pixels)
        for i in range(len(data_dict['data'])):
            xdata = data_dict['data'][i]
            dimensional_calibrations = xdata.dimensional_calibrations
            dimensional_calibrations[0] = Calibration.Calibration(**self.scan_calibrations[1])
            xdata._set_dimensional_calibrations(dimensional_calibrations)
            data_dict['data'][i] = xdata[flyback_pixels:]
        return data_dict
        # this is hopefully not needed anymore
#        images = []
#        for i in range(len(self.spectrum_parameters)):
#            self.shift_x(self.spectrum_parameters[i]['offset_x'])
#            self.shift_y(self.spectrum_parameters[i]['offset_y'])
#            self.adjust_focus(self.spectrum_parameters[i]['offset_x'])
#            if i == 0:
#                if first_line:
#                    res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels)
#                    images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
#                else:
#                    res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels + flyback_pixels-1)
#                    res['data'] = res['data'][flyback_pixels-1:]
#                    images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
#            elif False: #i == len(self.spectrum_parameters) - 1:
#                res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels + flyback_pixels-1)
#                #res['data'] = res['data'][flyback_pixels:-flyback_pixels]
#                res['data'] = res['data'][:-(flyback_pixels-1)]
#                images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
#            else:
#                res = self.camera._hardware_source._CameraHardwareSource__camera_adapter.camera.acquire_sequence(x_pixels + flyback_pixels)
#                #res['data'] = res['data'][flyback_pixels:]
#                res['data'] = res['data'][:-flyback_pixels]
#                images.append(HardwareSource.convert_data_element_to_data_and_metadata(res))
#        return images

    def process_and_send_data(self):
        while True:
            line_number, images = self.queue.get()
            print('got line')
            if images is None:
                break
            if self.__active_settings['stitch_spectra']:
                raise NotImplementedError
            else:
                images['line_number'] = line_number
                if hasattr(self, 'number_lines') and line_number == self.number_lines:
                    images['is_last_line'] = True
                self.new_data_ready_event.fire(images)
                print('processed line')
#            if self.data_item.data is None:
#                spectra = []
#                for k in range(len(images)):
#                    di = copy.copy(images[k])
#                    di._set_data(di.data[0])
#                    spectra.append(di)
#                crop_ranges = self.get_stitch_ranges(spectra)
#                data = np.zeros((self.number_lines, self.scan_parameters['size'][1], crop_ranges[-1][-1][-1]))
#            else:
#                data = self.data_item.data
#            row = []
#            for i in range(images[0].data.shape[0]):
#                spectra = []
#                for k in range(len(images)):
#                    di = copy.copy(images[k])
#                    di._set_data(di.data[i])
#                    spectra.append(di)
#                crop_ranges = self.get_stitch_ranges(spectra)
#                row.append(self.stitch_spectra(spectra, crop_ranges))
#            row = np.array(row)
#            data[line_number] = row
#            self.data_item.set_data(data)
            self.queue.task_done()

    def acquire_multi_eels_spectrum_image(self):
        self.__active_settings = copy.deepcopy(self.settings)
        self.__active_spectrum_parameters = copy.copy(self.spectrum_parameters)
        self.abort_event.clear()
        if not callable(self.__active_settings['x_shifter']) and self.__active_settings['x_shifter']:
            self.zeros['x'] = self.stem_controller.GetVal(self.__active_settings['x_shifter'])
        if not callable(self.__active_settings['y_shifter']) and self.__active_settings['y_shifter']:
            self.zeros['y'] = self.stem_controller.GetVal(self.__active_settings['y_shifter'])
        try:
            logging.debug("start")
            self.acquisition_state_changed_event.fire({"message": "start"})
            self.superscan.abort_playing()
            self.scan_parameters = self.superscan.get_record_frame_parameters()
            scan_max_size = 512
            self.scan_parameters["size"] = (min(scan_max_size, self.scan_parameters["size"][0]),
                                            min(scan_max_size, self.scan_parameters["size"][1]))
            self.scan_parameters["pixel_time_us"] = int(1000) #int(1000 * eels_camera_parameters["exposure_ms"] * 0.75)
            self.scan_parameters["external_clock_wait_time_ms"] = int(20000) #int(eels_camera_parameters["exposure_ms"]) + 100
            self.scan_parameters["external_clock_mode"] = 1
            self.scan_parameters["ac_frame_sync"] = False
            self.scan_parameters["ac_line_sync"] = False
            self.scan_calibrations = [{'offset': -self.scan_parameters['fov_size_nm'][0]/2,
                                       'scale': self.scan_parameters['fov_size_nm'][0]/self.scan_parameters['size'][0],
                                       'units': 'nm'},
                                      {'offset': -self.scan_parameters['fov_size_nm'][1]/2,
                                       'scale': self.scan_parameters['fov_size_nm'][1]/self.scan_parameters['size'][1],
                                       'units': 'nm'}]
            flyback_pixels = self.superscan.flyback_pixels
            self.number_lines = self.scan_parameters["size"][0]
            #self.scan_parameters["size"] = (len(self.spectrum_parameters), self.scan_parameters["size"][1])
            self.queue = queue.Queue()
            self.process_and_send_data_thread = threading.Thread(target=self.process_and_send_data)
            self.process_and_send_data_thread.start()
            if _has_superscan:
                _superscan.Scan_Settings_Property( _superscan.Scan_Property_Integer(len(self.__active_spectrum_parameters)), _superscan.Scan_Settings_LineRepeat())
            with contextlib.closing(contextlib.closing(RecordTask(self.superscan, self.scan_parameters))) as scan_task:
#                scan_center_y = self.scan_parameters["fov_nm"]/self.number_lines*(line-self.number_lines/2)
#                self.scan_parameters["center_nm"] = (scan_center_y, self.scan_parameters["center_nm"][1])
                for line in range(self.number_lines):
                    print(line)
                    res = self.acquire_multi_eels_line(self.scan_parameters["size"][1], flyback_pixels=flyback_pixels, first_line=line==0)
                    print('acquired line')
                    self.queue.put((line, res))
                    if self.abort_event.is_set():
                        break
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
            self.acquisition_state_changed_event.fire({"message": "exception", "content": str(e)})
            import traceback
            traceback.print_stack()
            print(e)
            raise
        finally:
            self.acquisition_state_changed_event.fire({"message": "end"})
            if _has_superscan:
                _superscan.Scan_Settings_Property(_superscan.Scan_Property_Integer(0), _superscan.Scan_Settings_LineRepeat())
            self.queue.join()
            self.queue.put((None, None))
            self.process_and_send_data_thread.join()
            self.queue = None
            self.process_and_send_data_thread = None
            self.shift_y(0)
            self.shift_x(0)
            self.adjust_focus(0)
            logging.debug("end")