# -*- coding: utf-8 -*-
"""
Created on Mon Oct 17 13:17:00 2016

@author: Andi
"""

# standard libraries
import logging
import threading

from multi_acquire_utils import MultiEELS
from nion.swift.model import HardwareSource
from nion.ui import Dialog

from nion.utils import Registry

class MultiEELSPanelDelegate(object):
    def __init__(self, api):
        self.__api = api
        self.panel_id = 'MultiEELS-Panel'
        self.panel_name = 'MultiAcquire'
        self.panel_positions = ['left', 'right']
        self.panel_position = 'right'
        self.api = api
        self.line_edit_widgets = {}
        self.push_button_widgets = {}
        self.label_widgets = {}
        self.MultiEELS = MultiEELS.MultiEELS()
        def low_level_parameter_changed(parameter):
            if parameter == 'added_spectrum':
                self.parameter_label_column.add(self.create_parameter_label_line(self.MultiEELS.spectrum_parameters[-1]))
            if parameter == 'removed_spectrum':
                self.parameter_label_column._widget.remove(self.parameter_label_column._widget.children[-1])
            if parameter == 'spectrum_parameters':
                for spectrum_parameters in self.MultiEELS.spectrum_parameters:
                    for name, field in self.label_widgets[spectrum_parameters['index']].items():
                        field.text = '{:g}'.format(spectrum_parameters[name])
                
        self.MultiEELS.on_low_level_parameter_changed = low_level_parameter_changed
        self.stem_controller = Registry.get_component('stem_controller')
        self.EELScam = self.stem_controller.eels_camera
        self.superscan = self.stem_controller.scan_controller
        self.settings_window_open = False
        self.parameters_window_open = False
        self.parameter_label_column = None

    def create_panel_widget(self, ui, document_controller):
        self.ui = ui
        self.document_controller = document_controller

        def start_clicked():
            if self.EELScam is None:
                logging.warn('Could not get EELS camera. Spectrum acquisition will not be possible')
                return
            if self.stem_controller is None:
                logging.warn('No instance of AS available.')
                return

            self.MultiEELS.as2 = self.stem_controller
            self.camera = self.EELScam._hardware_source._CameraHardwareSource__camera_adapter.camera
            self.MultiEELS.camera = self.EELScam
            self.MultiEELS.settings['x_shifter'] = self.camera.set_energy_shift
            self.MultiEELS.settings['x_shift_delay'] = 1
            def run_multi_eels():
                data_element = self.MultiEELS.acquire_multi_eels()
                data_and_metadata = HardwareSource.convert_data_element_to_data_and_metadata(data_element)
                def create_and_display_data_item():
                    data_item = document_controller.library.create_data_item_from_data_and_metadata(data_and_metadata)
                    document_controller.display_data_item(data_item)
                document_controller.queue_task(create_and_display_data_item)  # must occur on UI thread
            threading.Thread(target=run_multi_eels).start()

        def start_si_clicked():
            self.MultiEELS.document_controller = self.document_controller
            self.MultiEELS.as2 = self.stem_controller
            self.MultiEELS.superscan = self.superscan
            self.camera = self.EELScam._hardware_source._CameraHardwareSource__camera_adapter.camera
            self.MultiEELS.camera = self.EELScam
            self.MultiEELS.settings['x_shifter'] = self.camera.set_energy_shift
            self.MultiEELS.settings['x_shift_delay'] = 0.3
            threading.Thread(target=self.MultiEELS.acquire_multi_eels_spectrum_image).start()
        
        def settings_button_clicked():
            if not self.settings_window_open:
                self.settings_window_open = True
                self.show_config_box()
        
        def change_parameters_button_clicked():
            if not self.parameters_window_open:
                self.parameters_window_open = True
                self.show_change_parameters_box()
                
        change_parameters_row = ui.create_row_widget()
        change_parameters_button = ui.create_push_button_widget('Change...')
        change_parameters_button.on_clicked = change_parameters_button_clicked
        change_parameters_row.add_spacing(5)
        change_parameters_row.add(ui.create_label_widget('Current parameters:'))
        change_parameters_row.add_stretch()
        change_parameters_row.add_spacing(5)
        change_parameters_row.add(change_parameters_button)
        change_parameters_row.add_spacing(20)
        
        parameter_description_row = ui.create_row_widget()
        parameter_description_row.add_spacing(5)
        parameter_description_row.add(ui.create_label_widget('#'))
        parameter_description_row.add_spacing(5)
        parameter_description_row.add(ui.create_label_widget('X Offset (eV)'))
        parameter_description_row.add_spacing(5)
        parameter_description_row.add(ui.create_label_widget('Y Offset (px)'))
        parameter_description_row.add_spacing(5)
        parameter_description_row.add(ui.create_label_widget('Exposure (ms)'))
        parameter_description_row.add_spacing(5)
        
        settings_row = ui.create_row_widget()
        settings_button = ui.create_push_button_widget('Settings...')
        settings_button.on_clicked = settings_button_clicked
        settings_row.add_stretch()
        settings_row.add_spacing(5)
        settings_row.add(settings_button)
        settings_row.add_spacing(20)
        
        start_button = ui.create_push_button_widget('Start MultiEELS')
        start_button.on_clicked = start_clicked
        start_si_button = ui.create_push_button_widget('Start MultiEELS spectrum image')
        start_si_button.on_clicked = start_si_clicked
        start_row = ui.create_row_widget()
        start_row.add_spacing(5)
        start_row.add(start_button)
        start_row.add_spacing(15)
        start_row.add(start_si_button)
        start_row.add_spacing(5)
        start_row.add_stretch()

        column = ui.create_column_widget()
        column.add(change_parameters_row)
        column.add_spacing(5)
        column.add(parameter_description_row)
        column.add_spacing(5)
        self.parameter_label_column = ui.create_column_widget()
        for spectrum_parameters in self.MultiEELS.spectrum_parameters:
            line = self.create_parameter_label_line(spectrum_parameters)
            self.parameter_label_column.add(line)
            #column.add_spacing(10)
        column.add(self.parameter_label_column)
        column.add_spacing(5)
        column.add(settings_row)
        column.add_spacing(5)
        column.add(start_row)
        column.add_spacing(5)
        column.add_stretch()
        return column
    
    def create_parameter_label_line(self, spectrum_parameters):
        row = self.ui.create_row_widget()
        column = self.ui.create_column_widget()
        widgets = {}
        
        index = self.ui.create_label_widget('{:g}'.format(spectrum_parameters['index']))
        offset_x = self.ui.create_label_widget('{:g}'.format(spectrum_parameters['offset_x']))
        offset_y = self.ui.create_label_widget('{:g}'.format(spectrum_parameters['offset_y']))
        exposure_ms = self.ui.create_label_widget('{:g}'.format(spectrum_parameters['exposure_ms']))
        
        widgets['index'] = index
        widgets['offset_x'] = offset_x
        widgets['offset_y'] = offset_y
        widgets['exposure_ms'] = exposure_ms

        row.add_spacing(5)
        row.add(index)
        row.add_spacing(5)        
        row.add(offset_x)
        row.add_spacing(10)
        row.add(offset_y)
        row.add_spacing(10)
        row.add(exposure_ms)
        row.add_spacing(5)    
        
        self.label_widgets[spectrum_parameters['index']] = widgets
        
        column.add(row)
        column.add_spacing(10)
        
        return column

    def create_spectrum_parameter_line(self, spectrum_parameters):
        column = self.ui.create_column_widget()
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
        
        column.add(row)
        column.add_spacing(12)

        return column

    def show_config_box(self):
        dc = self.document_controller._document_controller

        class ConfigDialog(Dialog.OkCancelDialog):

            def __init__(self, ui, MultiEELSGUI):
                super(ConfigDialog, self).__init__(ui, include_cancel=False)
                def report_window_close():
                    MultiEELSGUI.settings_window_open = False
                self.on_accept = report_window_close
                self.on_reject = report_window_close
                
                def x_shift_strength_finished(text):
                    try:
                        newvalue = float(text)
                    except ValueError:
                        pass
                    else:
                        MultiEELSGUI.MultiEELS.settings['x_units_per_ev'] = newvalue
                    finally:
                        x_shift_strength_field.text = '{:g}'.format(MultiEELSGUI.MultiEELS.settings['x_units_per_ev'])
                
                def y_shift_strength_finished(text):
                    try:
                        newvalue = float(text)
                    except ValueError:
                        pass
                    else:
                        MultiEELSGUI.MultiEELS.settings['y_units_per_px'] = newvalue
                    finally:
                        y_shift_strength_field.text = '{:g}'.format(MultiEELSGUI.MultiEELS.settings['y_units_per_px'])
                
                def x_shift_delay_finished(text):
                    try:
                        newvalue = float(text)
                    except ValueError:
                        pass
                    else:
                        MultiEELSGUI.MultiEELS.settings['x_shift_delay'] = newvalue
                    finally:
                        x_shift_delay_field.text = '{:g}'.format(MultiEELSGUI.MultiEELS.settings['x_shift_delay'])
                
                def y_shift_delay_finished(text):
                    try:
                        newvalue = float(text)
                    except ValueError:
                        pass
                    else:
                        MultiEELSGUI.MultiEELS.settings['y_shift_delay'] = newvalue
                    finally:
                        y_shift_delay_field.text = '{:g}'.format(MultiEELSGUI.MultiEELS.settings['y_shift_delay'])
                
                def align_y_checkbox_changed(check_state):
                    MultiEELSGUI.MultiEELS.settings['y_align'] = check_state == 'checked'
                    
                def saturation_value_finished(text):
                    try:
                        newvalue = float(text)
                    except ValueError:
                        pass
                    else:
                        MultiEELSGUI.MultiEELS.settings['saturation_value'] = newvalue
                    finally:
                        saturation_value_field.text = '{:g}'.format(MultiEELSGUI.MultiEELS.settings['saturation_value'])
                    

                column = self.ui.create_column_widget()                
                row1 = self.ui.create_row_widget()
                row2 = self.ui.create_row_widget()
                row3 = self.ui.create_row_widget()
                
                x_shift_strength_label = self.ui.create_label_widget('X shifter strength (units/ev): ')
                x_shift_strength_field = self.ui.create_line_edit_widget()
                x_shift_delay_label = self.ui.create_label_widget('X shifter delay (s): ')
                x_shift_delay_field = self.ui.create_line_edit_widget()
                y_shift_strength_label = self.ui.create_label_widget('Y shifter strength (units/px): ')
                y_shift_strength_field = self.ui.create_line_edit_widget()
                y_shift_delay_label = self.ui.create_label_widget('Y shifter delay (s): ')
                y_shift_delay_field = self.ui.create_line_edit_widget()
                align_y_checkbox = self.ui.create_check_box_widget('Y-align spectra ')
                saturation_value_label = self.ui.create_label_widget('Camera saturation value: ')
                saturation_value_field = self.ui.create_line_edit_widget()
                
                row1.add_spacing(5)
                row1.add(x_shift_strength_label)
                row1.add(x_shift_strength_field)
                row1.add_spacing(5)
                row1.add(x_shift_delay_label)
                row1.add(x_shift_delay_field)
                row1.add_spacing(5)
                row1.add_stretch()
                
                row2.add_spacing(5)
                row2.add(y_shift_strength_label)
                row2.add(y_shift_strength_field)
                row2.add_spacing(5)
                row2.add(y_shift_delay_label)
                row2.add(y_shift_delay_field)
                row2.add_spacing(5)
                row2.add_stretch()
                
                row3.add_spacing(5)
                row3.add(align_y_checkbox)
                row3.add_spacing(20)
                row3.add(saturation_value_label)
                row3.add(saturation_value_field)
                row3.add_spacing(5)
                row3.add_stretch()
                
                column.add(row1)
                column.add_spacing(5)
                column.add(row2)
                column.add_spacing(5)
                column.add(row3)
                column.add_stretch()
                
                self.content.add_spacing(5)
                self.content.add(column)
                self.content.add_spacing(5)
                
                align_y_checkbox.checked = MultiEELSGUI.MultiEELS.settings['y_align']
                x_shift_strength_finished('')
                y_shift_strength_finished('')
                x_shift_delay_finished('')
                y_shift_delay_finished('')
                saturation_value_finished('')
                
                align_y_checkbox.on_check_state_changed = align_y_checkbox_changed
                x_shift_strength_field.on_editing_finished = x_shift_strength_finished
                y_shift_strength_field.on_editing_finished = y_shift_strength_finished
                x_shift_delay_field.on_editing_finished = x_shift_delay_finished
                y_shift_delay_field.on_editing_finished = y_shift_delay_finished

        ConfigDialog(dc.ui, self).show()

    def show_change_parameters_box(self):
        dc = self.document_controller._document_controller

        class ConfigDialog(Dialog.OkCancelDialog):

            def __init__(self, ui, MultiEELSGUI):
                super(ConfigDialog, self).__init__(ui, include_cancel=False)
                def report_window_close():
                    MultiEELSGUI.parameters_window_open = False
                self.on_accept = report_window_close
                self.on_reject = report_window_close
                
                def add_spectrum_clicked():
                    MultiEELSGUI.MultiEELS.add_spectrum()
                    column.add(MultiEELSGUI.create_spectrum_parameter_line(MultiEELSGUI.MultiEELS.spectrum_parameters[-1]))
                
                def remove_spectrum_clicked():
                    MultiEELSGUI.MultiEELS.remove_spectrum()
                    column._widget.remove(column._widget.children[-1])
                
                column = MultiEELSGUI.ui.create_column_widget()
                column.add_spacing(5)
                for spectrum_parameters in MultiEELSGUI.MultiEELS.spectrum_parameters:
                    column.add(MultiEELSGUI.create_spectrum_parameter_line(spectrum_parameters))
                
                row = ui.create_row_widget()
                add_spectrum_button = ui.create_push_button_widget('+')
                remove_spectrum_button = ui.create_push_button_widget('-')
                add_spectrum_button.on_clicked = add_spectrum_clicked
                remove_spectrum_button.on_clicked = remove_spectrum_clicked
                row.add_spacing(5)
                row.add_stretch()
                row.add(add_spectrum_button)
                row.add_spacing(5)
                row.add(remove_spectrum_button)
                row.add_spacing(5)
                row.add_stretch()
                
                self.content.add_spacing(5)
                self.content.add(column._widget)
                self.content.add_spacing(5)
                self.content.add(row)
                self.content.add_spacing(10)

        ConfigDialog(dc.ui, self).show()

class MultiEELSExtension(object):
    extension_id = 'univie.multieels'

    def __init__(self, api_broker):
        api = api_broker.get_api(version='1', ui_version='1')
        self.__panel_ref = api.create_panel(MultiEELSPanelDelegate(api))

    def close(self):
        self.__panel_ref.close()
        self.__panel_ref = None