# -*- coding: utf-8 -*-
"""
Created on Mon Oct 17 13:17:00 2016

@author: Andi
"""

# standard libraries
import logging
import threading
from queue import Empty

from multi_acquire_utils import MultiEELS
from nion.ui import Dialog
from nion.utils import Registry
from nion.data import xdata_1_0 as xd
from nion.data import Calibration

from multi_acquire_utils import ColorCycle

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
        self.__acquisition_state_changed_event_listener = self.MultiEELS.acquisition_state_changed_event.listen(self.acquisition_state_changed)
        self.__new_data_ready_event_listener = self.MultiEELS.new_data_ready_event.listen(self.update_result)
        self.stem_controller = None
        self.EELScam = None
        self.superscan = None
        self.settings_window_open = False
        self.parameters_window_open = False
        self.parameter_label_column = None
        self.result_data_items = []
        self.__result_data_items_refs = []
        self.__acquisition_running = False

    def create_result_data_item(self, data_dict):
        if data_dict.get('stitched_data'):
            data_item = self.document_controller.library.create_data_item_from_data_and_metadata(data_dict['data'][0],
                                                                                          title='MultiEELS (stitched)')
            metadata = data_item.metadata
            metadata['MultiEELS'] = data_dict['parameters']
            data_item.set_metadata(metadata)
        elif not data_dict.get('stitched_data'):
            display_layers = []
            ColorCycle.reset_color_cycle()
            display_item = None
            for i in range(len(data_dict['data'])):
                index = data_dict['parameters'][i]['index']
                if i == 0 and data_dict['data'][i].is_data_1D:
                    data_item = self.document_controller.library.create_data_item_from_data_and_metadata(
                                                                                        data_dict['data'][i],
                                                                                        title='MultiEELS (stacked)')
                    display_item = self.__api.library._document_model.get_display_item_for_data_item(data_item._data_item)
                    new_data_item = data_item
                else:
                    new_data_item = self.document_controller.library.create_data_item_from_data_and_metadata(
                                                                                data_dict['data'][i],
                                                                                title='MultiEELS #{:d}'.format(index))
                metadata = new_data_item.metadata
                metadata['MultiEELS'] = data_dict['parameters'][i]
                new_data_item.set_metadata(metadata)
                if display_item:
                    display_item.append_display_data_channel_for_data_item(new_data_item._data_item)
                    start_ev = data_dict['parameters'][i]['start_ev']
                    end_ev = data_dict['parameters'][i]['end_ev']
                    display_layers.append({'label': '#{:d}: {:g}-{:2g} eV'.format(index, start_ev, end_ev),
                                           'data_index': i,
                                           'fill_color': ColorCycle.get_next_color()})
            if display_item:
                display_item.display_layers = display_layers
                display_item.set_display_property("legend_position", "top-right")
                display_item.title = 'MultiEELS (stacked)'

    def acquisition_state_changed(self, info_dict):
        if info_dict.get('message') == 'start':
            self.__acquisition_running = True
            def update_button():
                self.start_si_button.text = 'Abort MultiEELS spectrum image'
            self.__api.queue_task(update_button)
        elif info_dict.get('message') == 'end':
            self.__acquisition_running = False
            def update_button():
                self.start_si_button.text = 'Start MultiEELS spectrum image'
            self.__api.queue_task(update_button)

        elif info_dict.get('message') == 'exception':
            self.__close_data_item_refs()

    def __close_data_item_refs(self):
        for item_ref in self.__result_data_items_refs:
                item_ref.__exit__(None, None, None)
        self.__result_data_items_refs = []
#        for item in self.result_data_items:
#            try:
#                while True:
#                    item.xdata.decrement_data_ref_count()
#            except AssertionError:
#                pass
        self.result_data_items = []

    def update_result(self, data_dict):
        print('got from disp queue')
        def create_or_update_data_items():
            if not self.result_data_items:
                print('here')
                self.result_data_items = []
                self.__result_data_items_refs = []
                xdata_list = data_dict.pop('data')
                for i in range(len(xdata_list)):
                    xdata = xdata_list[i]
                    new_xdata = xd.reshape(xdata, (-1,) + xdata.data_shape)
                    dimensional_calibrations = new_xdata.dimensional_calibrations
                    dimensional_calibrations[0] = Calibration.Calibration(**self.MultiEELS.scan_calibrations[0])
                    if data_dict.get('stitched_data'):
                        new_data_item = self.__api.library.create_data_item_from_data_and_metadata(new_xdata,
                                                                                        title='MultiEELS (stitched)')
                        metadata = xdata.metadata
                        metadata['MultiEELS'] = data_dict['parameters']
                    else:
                        parms = data_dict['parameters'][i]
                        new_data_item = self.__api.library.create_data_item_from_data_and_metadata(new_xdata,
                                                                      title='MultiEELS #{:d}'.format(parms['index']))
                        metadata = xdata.metadata
                        metadata['MultiEELS'] = data_dict['parameters'][i]

                    new_data_item.set_metadata(metadata)
                    new_data_item_ref = self.__api.library.data_ref_for_data_item(new_data_item)
                    new_data_item_ref.__enter__()
                    self.__result_data_items_refs.append(new_data_item_ref)
                    #new_data_item_ref = None
                    self.result_data_items.append(new_data_item)
                    #new_data_item = None
#                    try:
#                        while True:
#                            xdata.decrement_data_ref_count()
#                    except AssertionError:
#                        pass
                #xdata_list = None
            else:
                print('here2')
                xdata_list = data_dict.pop('data')
                for i in range(len(xdata_list)):
                    new_xdata = xd.concatenate([self.result_data_items[i].xdata,
                                                xd.reshape(xdata_list[i], (-1,) + xdata_list[i].data_shape)], axis=0)
                    #old_xdata = self.result_data_items[i].xdata
                    self.result_data_items[i].set_data_and_metadata(new_xdata)
                    #new_xdata = None
                    new_data_item_ref = self.__api.library.data_ref_for_data_item(self.result_data_items[i])
                    new_data_item_ref.__enter__()
                    self.__result_data_items_refs[i].__exit__(None, None, None)
                    self.__result_data_items_refs[i] = new_data_item_ref
                    #new_data_item_ref = None
#                    try:
#                        while True:
#                            old_xdata.decrement_data_ref_count()
#                    except AssertionError:
#                        pass
#                    #old_xdata = None
#                    try:
#                        while True:
#                            xdata_list[i].decrement_data_ref_count()
#                    except AssertionError:
#                        pass
                #xdata_list = None
            print('finished display')
            if data_dict.get('is_last_line'):
                #self.__close_data_item_refs()
                threading.Thread(target=self.__close_data_item_refs, daemon=True).start()
        self.__api.queue_task(create_or_update_data_items)

    def create_panel_widget(self, ui, document_controller):
        self.ui = ui
        self.document_controller = document_controller

        def start_clicked():
            self.stem_controller = Registry.get_component('stem_controller')
            self.EELScam = self.stem_controller.eels_camera
            self.superscan = self.stem_controller.scan_controller
            self.MultiEELS.stem_controller = self.stem_controller
            #self.camera = self.EELScam._hardware_source._CameraHardwareSource__camera_adapter.camera
            self.MultiEELS.camera = self.EELScam
            #self.MultiEELS.settings['x_shifter'] = self.camera.set_energy_shift
            #self.MultiEELS.settings['x_shift_delay'] = 1
            def run_multi_eels():
                data_dict = self.MultiEELS.acquire_multi_eels_spectrum()
                def create_and_display_data_item():
                    self.create_result_data_item(data_dict)
                document_controller.queue_task(create_and_display_data_item)  # must occur on UI thread
            threading.Thread(target=run_multi_eels, daemon=True).start()

        def start_si_clicked():
            if self.__acquisition_running:
                self.MultiEELS.abort_event.set()
            else:
                self.stem_controller = Registry.get_component('stem_controller')
                self.EELScam = self.stem_controller.eels_camera
                self.superscan = self.stem_controller.scan_controller
                self.MultiEELS.stem_controller = self.stem_controller
                #self.camera = self.EELScam._hardware_source._CameraHardwareSource__camera_adapter.camera
                self.MultiEELS.camera = self.EELScam
                self.MultiEELS.superscan = self.superscan
                #self.MultiEELS.settings['x_shifter'] = self.camera.set_energy_shift
                #self.MultiEELS.settings['x_shift_delay'] = 1
                self.__close_data_item_refs()
                threading.Thread(target=self.MultiEELS.acquire_multi_eels_spectrum_image, daemon=True).start()

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
        parameter_description_row.add(ui.create_label_widget('Frames'))
        parameter_description_row.add_spacing(5)

        settings_row = ui.create_row_widget()
        settings_button = ui.create_push_button_widget('Settings...')
        settings_button.on_clicked = settings_button_clicked
        settings_row.add_stretch()
        settings_row.add_spacing(5)
        settings_row.add(settings_button)
        settings_row.add_spacing(20)

        self.start_button = ui.create_push_button_widget('Start MultiEELS')
        self.start_button.on_clicked = start_clicked
        self.start_si_button = ui.create_push_button_widget('Start MultiEELS spectrum image')
        self.start_si_button.on_clicked = start_si_clicked
        start_row = ui.create_row_widget()
        start_row.add_spacing(5)
        start_row.add(self.start_button)
        start_row.add_spacing(15)
        start_row.add(self.start_si_button)
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
        frames = self.ui.create_label_widget('{:.0f}'.format(spectrum_parameters['frames']))

        widgets['index'] = index
        widgets['offset_x'] = offset_x
        widgets['offset_y'] = offset_y
        widgets['exposure_ms'] = exposure_ms
        widgets['frames'] = frames

        row.add_spacing(5)
        row.add(index)
        row.add_spacing(5)
        row.add(offset_x)
        row.add_spacing(10)
        row.add(offset_y)
        row.add_spacing(10)
        row.add(exposure_ms)
        row.add_spacing(10)
        row.add(frames)
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
        descriptor_column.add_spacing(5)
        descriptor_column.add(self.ui.create_label_widget('X offset (eV):'))
        descriptor_column.add_spacing(5)
        descriptor_column.add(self.ui.create_label_widget('Y offset (px):'))
        descriptor_column.add_spacing(5)
        descriptor_column.add(self.ui.create_label_widget('Exposure (ms):'))
        descriptor_column.add_spacing(5)
        descriptor_column.add(self.ui.create_label_widget('Frames:'))
        descriptor_column.add_spacing(5)
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

        frames = self.ui.create_line_edit_widget()
        frames.text = str(spectrum_parameters['frames'])
        frames.on_editing_finished = lambda text: self.MultiEELS.set_frames(spectrum_parameters['index'], int(text))
        widgets['frames'] = frames

        value_column.add_spacing(5)
        value_column.add(spectrum_no)
        value_column.add_spacing(5)
        value_column.add(offset_x)
        value_column.add_spacing(1)
        value_column.add(offset_y)
        value_column.add_spacing(1)
        value_column.add(exposure_ms)
        value_column.add_spacing(1)
        value_column.add(frames)
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

        class ConfigDialog(Dialog.ActionDialog):

            def __init__(self, ui, MultiEELSGUI):
                super(ConfigDialog, self).__init__(ui)
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

                def auto_dark_subtract_checkbox_changed(check_state):
                    MultiEELSGUI.MultiEELS.settings['auto_dark_subtract'] = check_state == 'checked'

                def bin_1D_checkbox_changed(check_state):
                    MultiEELSGUI.MultiEELS.settings['bin_spectra'] = check_state == 'checked'

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
                row4 = self.ui.create_row_widget()

                x_shift_strength_label = self.ui.create_label_widget('X shifter strength (units/ev): ')
                x_shift_strength_field = self.ui.create_line_edit_widget()
                x_shift_delay_label = self.ui.create_label_widget('X shifter delay (s): ')
                x_shift_delay_field = self.ui.create_line_edit_widget()
                y_shift_strength_label = self.ui.create_label_widget('Y shifter strength (units/px): ')
                y_shift_strength_field = self.ui.create_line_edit_widget()
                y_shift_delay_label = self.ui.create_label_widget('Y shifter delay (s): ')
                y_shift_delay_field = self.ui.create_line_edit_widget()
                align_y_checkbox = self.ui.create_check_box_widget('Y-align spectra ')
                auto_dark_subtract_checkbox = self.ui.create_check_box_widget('Auto dark subtraction ')
                bin_1D_checkbox = self.ui.create_check_box_widget('Bin data in y direction ')
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
                row3.add(auto_dark_subtract_checkbox)
                row3.add_spacing(5)
                row3.add_stretch()

                row4.add_spacing(5)
                row4.add(bin_1D_checkbox)
                row4.add_spacing(20)
                row4.add(saturation_value_label)
                row4.add(saturation_value_field)
                row4.add_spacing(5)
                row4.add_stretch()

                column.add(row1)
                column.add_spacing(5)
                column.add(row2)
                column.add_spacing(5)
                column.add(row3)
                column.add_spacing(5)
                column.add(row4)
                column.add_stretch()

                self.content.add_spacing(5)
                self.content.add(column)
                self.content.add_spacing(5)

                align_y_checkbox.checked = MultiEELSGUI.MultiEELS.settings['y_align']
                auto_dark_subtract_checkbox.checked = MultiEELSGUI.MultiEELS.settings['auto_dark_subtract']
                bin_1D_checkbox.checked = MultiEELSGUI.MultiEELS.settings['bin_spectra']
                x_shift_strength_finished('')
                y_shift_strength_finished('')
                x_shift_delay_finished('')
                y_shift_delay_finished('')
                saturation_value_finished('')

                align_y_checkbox.on_check_state_changed = align_y_checkbox_changed
                auto_dark_subtract_checkbox.on_check_state_changed = auto_dark_subtract_checkbox_changed
                bin_1D_checkbox.on_check_state_changed = bin_1D_checkbox_changed
                x_shift_strength_field.on_editing_finished = x_shift_strength_finished
                y_shift_strength_field.on_editing_finished = y_shift_strength_finished
                x_shift_delay_field.on_editing_finished = x_shift_delay_finished
                y_shift_delay_field.on_editing_finished = y_shift_delay_finished

            def about_to_close(self, geometry: str, state: str) -> None:
                if self.on_reject:
                    self.on_reject()
                super().about_to_close(geometry, state)

        ConfigDialog(dc.ui, self).show()

    def show_change_parameters_box(self):
        dc = self.document_controller._document_controller

        class ConfigDialog(Dialog.ActionDialog):

            def __init__(self, ui, MultiEELSGUI):
                super(ConfigDialog, self).__init__(ui)
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

            def about_to_close(self, geometry: str, state: str) -> None:
                if self.on_reject:
                    self.on_reject()
                super().about_to_close(geometry, state)

        ConfigDialog(dc.ui, self).show()

class MultiEELSExtension(object):
    extension_id = 'nion.extension.multiacquire'

    def __init__(self, api_broker):
        api = api_broker.get_api(version='1', ui_version='1')
        self.__panel_ref = api.create_panel(MultiEELSPanelDelegate(api))

    def close(self):
        self.__panel_ref.close()
        self.__panel_ref = None