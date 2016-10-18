# -*- coding: utf-8 -*-
"""
Created on Mon Oct 17 13:17:00 2016

@author: Andi
"""

# standard libraries
import logging
import threading

from . import MultiEELS
from nion.swift.model import HardwareSource


class MultiEELSPanelDelegate(object):
    
    
    def __init__(self, api):
        self.__api = api
        self.panel_id = 'MultiEELS-Panel'
        self.panel_name = 'MultiEELS'
        self.panel_positions = ['left', 'right']
        self.panel_position = 'right'
        #self.adocument_controller = None
        self.input_field = None
        self.send_button = None
        self.api=api
        self.history = []
        self.current_position = 0
        self.locals = locals()
        self.globals = globals()
        self.line_edit_widgets = {}
        self.push_button_widgets = {}
        self.MultiEELS = MultiEELS.MultiEELS()
        def low_level_parameter_changed(parameter):
            print(getattr(self.MultiEELS, parameter))
        self.MultiEELS.on_low_level_parameter_changed = low_level_parameter_changed
        self.EELScam = self.api.get_hardware_source_by_id('andor_camera', '1')
        self.as2 = self.api.get_instrument_by_id('autostem_controller', '1')
    
    def create_panel_widget(self, ui, document_controller):
        self.ui = ui
        self.document_controller = document_controller
        
        def start_clicked():
            if self.EELScam is None:
                logging.warn('Could not get EELS camera. Spectrum acquisition will not be possible')
                return
            if self.as2 is None:
                logging.warn('No instance of AS available.')
                return
                
            self.MultiEELS.as2 = self.as2
            self.camera = self.EELScam._hardware_source._CameraHardwareSource__camera_adapter.camera
            self.MultiEELS.camera = self.EELScam
            self.MultiEELS.settings['x_shifter'] = self.camera.set_energy_shift
            self.MultiEELS.settings['x_shift_delay'] = 0.2
            def run_multi_eels():
                data_element = self.MultiEELS.acquire_multi_eels()
                data_and_metadata = HardwareSource.convert_data_element_to_data_and_metadata(data_element)
                def create_and_display_data_item():
                    data_item = document_controller.library.create_data_item_from_data_and_metadata(data_and_metadata)
                    document_controller.display_data_item(data_item)
                document_controller.queue_task(create_and_display_data_item)  # must occur on UI thread
            threading.Thread(run_multi_eels()).start()
                
        
        start_button = ui.create_push_button_widget('Start MultiEELS')
        start_button.on_clicked = start_clicked
        start_row = ui.create_row_widget()
        start_row.add_spacing(5)
        start_row.add(start_button)
        start_row.add_spacing(5)
        start_row.add_stretch()
        
        column = ui.create_column_widget()
        for spectrum_parameters in self.MultiEELS.spectrum_parameters:
            column.add(self.create_spectrum_parameter_line(spectrum_parameters))
            column.add_spacing(12)
        column.add_spacing(5)
        column.add(start_row)
        column.add_spacing(5)
        column.add_stretch()
        return column
        
    def create_spectrum_parameter_line(self, spectrum_parameters):
        row = self.ui.create_row_widget()
        widgets = {}
        descriptor_column = self.ui.create_column_widget()
        value_column = self.ui.create_column_widget()
        
        descriptor_column.add_spacing(5)        
        descriptor_column.add(self.ui.create_label_widget('Spectrum #:'))
        descriptor_column.add_spacing(8)
        descriptor_column.add(self.ui.create_label_widget('X offset (eV):'))
        descriptor_column.add_spacing(8)
        descriptor_column.add(self.ui.create_label_widget('Y offset (px):'))
        descriptor_column.add_spacing(8)
        descriptor_column.add(self.ui.create_label_widget('Exposure (ms):'))
        descriptor_column.add_spacing(8)
        descriptor_column.add_stretch()
        
        spectrum_no = self.ui.create_label_widget(str(spectrum_parameters['index']))
        
        offset_x = self.ui.create_line_edit_widget()
        offset_x.text = str(spectrum_parameters['offset_x'])
        offset_x.on_editing_finished = lambda text: self.MultiEELS.set_offset_x(spectrum_parameters['index'], float(text))
        widgets['offset_x'] = offset_x
        
        offset_y = self.ui.create_line_edit_widget()
        offset_y.text = str(spectrum_parameters['offset_y'])
        offset_y.on_editing_finished = lambda text: self.MultiEELS.set_offset_y(spectrum_parameters['index'], float(text))
        widgets['offset_y'] = offset_y            
        
        exposure_ms = self.ui.create_line_edit_widget()
        exposure_ms.text = str(spectrum_parameters['exposure_ms'])
        exposure_ms.on_editing_finished = lambda text: self.MultiEELS.set_exposure_ms(spectrum_parameters['index'], float(text))
        widgets['exposure_ms'] = exposure_ms
        
        value_column.add_spacing(5)        
        value_column.add(spectrum_no)
        value_column.add_spacing(5)
        value_column.add(offset_x)
        value_column.add_spacing(1)
        value_column.add(offset_y)
        value_column.add_spacing(1)
        value_column.add(exposure_ms)
        value_column.add_stretch()
        
        row.add_spacing(5)        
        row.add(descriptor_column)
        row.add_spacing(5)
        row.add(value_column)
        row.add_spacing(5)
        row.add_stretch()
        
        self.line_edit_widgets[spectrum_parameters['index']] = widgets
        
        return row
        
class MultiEELSExtension(object):
    extension_id = 'univie.multieels'
    
    def __init__(self, api_broker):
        api = api_broker.get_api(version='1', ui_version='1')
        self.__panel_ref = api.create_panel(MultiEELSPanelDelegate(api))
    
    def close(self):
        self.__panel_ref.close()
        self.__panel_ref = None