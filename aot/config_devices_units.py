# -*- coding: utf-8 -*-
#
#  config_devices_units.py - AoT device unit settings
#

from flask_babel import lazy_gettext


# Measurement information
# First unit in list is the default unit when Input is created
MEASUREMENTS = {
    'acceleration': {
        'name': lazy_gettext('Acceleration'),
        'meas': 'acceleration',
        'units': ['g_force', 'm_s_s']},
    'acceleration_x': {
        'name': "{} (X)".format(lazy_gettext('Acceleration')),
        'meas': 'acceleration_x',
        'units': ['g_force', 'm_s_s']},
    'acceleration_y': {
        'name': "{} (Y)".format(lazy_gettext('Acceleration')),
        'meas': 'acceleration_y',
        'units': ['g_force', 'm_s_s']},
    'acceleration_z': {
        'name': "{} (Z)".format(lazy_gettext('Acceleration')),
        'meas': 'acceleration_z',
        'units': ['g_force', 'm_s_s']},
    'adc': {
        'name': lazy_gettext('ADC'),
        'meas': 'adc',
        'units': ['none']},
    'altitude': {
        'name': lazy_gettext('Altitude'),
        'meas': 'altitude',
        'units': ['m', 'ft']},
    'angle': {
        'name': lazy_gettext('Angle'),
        'meas': 'angle',
        'units': ['degree']},
    'battery': {
        'name': lazy_gettext('Battery'),
        'meas': 'battery',
        'units': ['percent', 'decimal', 'bool']},
    'boolean': {
        'name': lazy_gettext('Boolean'),
        'meas': 'boolean',
        'units': ['bool']},
    'brightness': {
        'name': lazy_gettext('Brightness'),
        'meas': 'brightness',
        'units': ['percent']},
    'co2': {
        'name': lazy_gettext('Carbon Dioxide'),
        'meas': 'co2',
        'units': ['ppm', 'ppb', 'percent']},
    'color_red': {
        'name': "{} ({})".format(lazy_gettext('Color'), lazy_gettext('Red')),
        'meas': 'color_red',
        'units': ['eight_bit_color']},
    'color_green': {
        'name': "{} ({})".format(lazy_gettext('Color'), lazy_gettext('Green')),
        'meas': 'color_green',
        'units': ['eight_bit_color']},
    'color_blue': {
        'name': "{} ({})".format(lazy_gettext('Color'), lazy_gettext('Blue')),
        'meas': 'color_blue',
        'units': ['eight_bit_color']},
    'color_temperature': {
        'name': lazy_gettext('Color Temperature'),
        'meas': 'color_temperature',
        'units': ['K']},
    'color_x': {
        'name': "{} (x)".format(lazy_gettext('Color')),
        'meas': 'color_x',
        'units': ['cie']},
    'color_y': {
        'name': "{} (y)".format(lazy_gettext('Color')),
        'meas': 'color_y',
        'units': ['cie']},
    'color_Y': {
        'name': "{} (Y)".format(lazy_gettext('Color')),
        'meas': 'color_Y',
        'units': ['cie']},
    'cpu_load_1m': {
        'name': "{} (1 {})".format(lazy_gettext('CPU Load'), lazy_gettext('Minute')),
        'meas': 'cpu_load',
        'units': ['cpu_load']},
    'cpu_load_5m': {
        'name': "{} (5 {})".format(lazy_gettext('CPU Load'), lazy_gettext('Minutes')),
        'meas': 'cpu_load',
        'units': ['cpu_load']},
    'cpu_load_15m': {
        'name': "{} (15 {})".format(lazy_gettext('CPU Load'), lazy_gettext('Minutes')),
        'meas': 'cpu_load',
        'units': ['cpu_load']},
    'dewpoint': {
        'name': lazy_gettext('Dewpoint'),
        'meas': 'temperature',
        'units': ['C', 'F', 'K']},
    'direction': {
        'name': lazy_gettext('Direction'),
        'meas': 'direction',
        'units': ['bearing']},
    'disk_space': {
        'name': lazy_gettext('Disk'),
        'meas': 'disk_space',
        'units': ['MB', 'kB', 'GB']},
    'dissolved_oxygen': {
        'name': lazy_gettext('Dissolved Oxygen'),
        'meas': 'dissolved_oxygen',
        'units': ['mg_L']},
    'duration_time': {
        'name': lazy_gettext('Duration'),
        'meas': 'duration_time',
        'units': ['s', 'minute', 'h', 'day']},
    'duty_cycle': {
        'name': lazy_gettext('Duty Cycle'),
        'meas': 'duty_cycle',
        'units': ['percent', 'decimal']},
    'edge': {
        'name': lazy_gettext('GPIO Edge'),
        'meas': 'edge',
        'units': ['bool']},
    'electrical_conductivity': {
        'name': lazy_gettext('Electrical Conductivity'),
        'meas': 'electrical_conductivity',
        'units': ['uS_cm']},
    'electrical_conductivity_soil': {
        'name': lazy_gettext('Electrical Conductivity (Soil)'),
        'meas': 'electrical_conductivity_soil',
        'units': ['dS_m']},
    'electrical_current': {
        'name': lazy_gettext('Electrical Current'),
        'meas': 'electrical_current',
        'units': ['A', 'mA']},
    'electrical_potential': {
        'name': lazy_gettext('Electrical Potential'),
        'meas': 'electrical_potential',
        'units': ['V', 'mV']},
    'energy': {
        'name': lazy_gettext('Energy'),
        'meas': 'energy',
        'units': ['kWh']},
    'frequency': {
        'name': lazy_gettext('Frequency'),
        'meas': 'frequency',
        'units': ['Hz', 'kHz', 'MHz']},
    'gpio_state': {
        'name': lazy_gettext('GPIO State'),
        'meas': 'gpio_state',
        'units': ['bool']},
    'hue': {
        'name': lazy_gettext('Hue'),
        'meas': 'hue',
        'units': ['degree']},
    'humidity': {
        'name': lazy_gettext('Humidity'),
        'meas': 'humidity',
        'units': ['decimal', 'percent', 'ppb', 'ppm', 'ppt']},
    'humidity_ratio': {
        'name': lazy_gettext('Humidity Ratio'),
        'meas': 'humidity_ratio',
        'units': ['kg_kg']},
    'ion_concentration': {
        'name': lazy_gettext('Ion Concentration'),
        'meas': 'ion_concentration',
        'units': ['pH']},
    'length': {
        'name': lazy_gettext('Length'),
        'meas': 'length',
        'units': ['ft', 'cm', 'm', 'mm', 'in']},
    'light': {
        'name': lazy_gettext('Light'),
        'meas': 'light',
        'units': ['full', 'ir', 'lux', 'klux']},
    'magnetic_flux_density': {
        'name': lazy_gettext('Magnetic Flux Density'),
        'meas': 'magnetic_flux_density',
        'units': ['uT']},
    'methane': {
        'name': lazy_gettext('Methane'),
        'meas': 'methane',
        'units': ['ppm', 'ppb', 'percent']},
    'moisture': {
        'name': lazy_gettext('Moisture'),
        'meas': 'moisture_leafwetness',
        'units': ['none', 'cb']},
    'o2': {
        'name': lazy_gettext('Oxygen'),
        'meas': 'o2',
        'units': ['ppt', 'ppm', 'ppb', 'percent']},
    'oxidation_reduction_potential': {
        'name': lazy_gettext('Oxidation Reduction Potential'),
        'meas': 'oxidation_reduction_potential',
        'units': ['mV', 'V']},
    'particulate_matter_1_0': {
        'name': 'PM1',
        'meas': 'particulate_matter_1_0',
        'units': ['ug_m3']},
    'particulate_matter_2_5': {
        'name': 'PM2.5',
        'meas': 'particulate_matter_2_5',
        'units': ['ug_m3']},
    'particulate_matter_10_0': {
        'name': 'PM10',
        'meas': 'particulate_matter_10_0',
        'units': ['ug_m3']},
    'pid_p_value': {
        'name': lazy_gettext('PID P-Value'),
        'meas': 'pid_value',
        'units': ['pid_value']},
    'pid_i_value': {
        'name': lazy_gettext('PID I-Value'),
        'meas': 'pid_value',
        'units': ['pid_value']},
    'pid_d_value': {
        'name': lazy_gettext('PID D-Value'),
        'meas': 'pid_value',
        'units': ['pid_value']},
    'position_open': {
        'name': lazy_gettext('Position Open'),
        'meas': 'position_open',
        'units': ['percent']},
    'power': {
        'name': lazy_gettext('Power'),
        'meas': 'power',
        'units': ['W']},
    'power_apparent': {
        'name': lazy_gettext('Apparent Power'),
        'meas': 'power_apparent',
        'units': ['va']},
    'power_factor': {
        'name': lazy_gettext('Power Factor'),
        'meas': 'power_factor',
        'units': ['unitless']},
    'power_reactive': {
        'name': lazy_gettext('Reactive Power'),
        'meas': 'power_reactive',
        'units': ['var']},
    'precipitation': {
        'name': lazy_gettext('강수'),
        'meas': 'precipitation',
        'units': ['mm', 'percent', 'in_h', 'mm_h', 'none']},  
    'pressure': {
        'name': lazy_gettext('Pressure'),
        'meas': 'pressure',
        'units': ['cm_water', 'psi', 'hPa', 'Pa', 'kPa', 'bar', 'kgf_cm2', 'inHg']},
    'pulse_width': {
        'name': lazy_gettext('Pulse Width'),
        'meas': 'pulse_width',
        'units': ['us']},
    'radiation_dose_rate': {
        'name': lazy_gettext('Radiation Dose Rate'),
        'meas': 'radiation_dose_rate',
        'units': ['cpm', 'uSv_hr']},
    'rate_volume': {
        'name': lazy_gettext('Volume Flow Rate'),
        'meas': 'rate_volume',
        'units': ['l_hr', 'l_min', 'l_s']},
    'resistance': {
        'name': lazy_gettext('Resistance'),
        'meas': 'resistance',
        'units': ['Ohm']},
    'rotation': {
        'name': lazy_gettext('Rotation'),
        'meas': 'rotation',
        'units': ['steps']},
    'rssi': {
        'name': lazy_gettext('RSSI'),
        'meas': 'rssi',
        'units': ['dBm']},
    'revolutions': {  # TODO: Move revolutions to rotations
        'name': lazy_gettext('Revolutions'),
        'meas': 'revolutions',
        'units': ['rpm']},
    'salinity': {
        'name': lazy_gettext('Salinity'),
        'meas': 'salinity',
        'units': ['ppt']},
    'saturation': {
        'name': lazy_gettext('Saturation'),
        'meas': 'saturation',
        'units': ['percent']},
    'setpoint': {
        'name': lazy_gettext('Setpoint'),
        'meas': 'setpoint',
        'units': ['setpoint']},
    'setpoint_band_min': {
        'name': lazy_gettext('Band Min'),
        'meas': 'setpoint_band_min',
        'units': ['setpoint']},
    'setpoint_band_max': {
        'name': lazy_gettext('Band Max'),
        'meas': 'setpoint_band_max',
        'units': ['setpoint']},
    'specific_enthalpy': {
        'name': lazy_gettext('Specific Enthalpy'),
        'meas': 'specific_enthalpy',
        'units': ['kJ_kg']},
    'snowfall': {
        'name': lazy_gettext('신적설'),
        'meas': 'snowfall',
        'units': ['cm']},
    'snr': {
        'name': lazy_gettext('SNR'),
        'meas': 'snr',
        'units': ['dB']},
    'specific_gravity': {
        'name': lazy_gettext('Specific Gravity'),
        'meas': 'specific_gravity',
        'units': ['unitless']},
    'specific_volume': {
        'name': lazy_gettext('Specific Volume'),
        'meas': 'specific_volume',
        'units': ['m3_kg']},
    'speed': {
        'name': lazy_gettext('Speed'),
        'meas': 'speed',
        'units': ['m_s', 'mph', 'kn']},
    # Removed: Replaced by soil_moisture_cb consolidation below
    'sky_condition': {
        'name': lazy_gettext('하늘상태'),
        'meas': 'sky_condition',
        'units': ['none', 'percent']},    
    'temperature': {
        'name': lazy_gettext('Temperature'),
        'meas': 'temperature',
        'units': ['C', 'F', 'K']},
    'total_dissolved_solids': {
        'name': lazy_gettext('Total Dissolved Solids'),
        'meas': 'total_dissolved_solids',
        'units': ['ppb', 'ppm']},
    'unitless': {
        'name': lazy_gettext('Unitless'),
        'meas': 'unitless',
        'units': ['none']},
    'uvi': {
        'name': lazy_gettext('Ultraviolet Index'),
        'meas': 'uvi',
        'units': ['index']},
    'vapor_pressure_deficit': {
        'name': lazy_gettext('Vapor Pressure Deficit'),
        'meas': 'vapor_pressure_deficit',
        'units': ['hPa', 'Pa', 'kPa']},
    'version': {
        'name': lazy_gettext('Version'),
        'meas': 'version',
        'units': ['none']},
    'voc': {
        'name': lazy_gettext('VOC'),
        'meas': 'voc',
        'units': ['ppb', 'ppm']},
    'volume': {
        'name': lazy_gettext('Volume'),
        'meas': 'volume',
        'units': ['l', 'ml']},
    'radiation': {
        'name': lazy_gettext('Solar Radiation'),
        'meas': 'radiation',
        'units': ['W_m2', 'J_cm2', 'umol_m2_s', 'lux', 'klux']},
    'visibility': {
        'name': lazy_gettext('Visibility'),
        'meas': 'visibility',
        'units': ['km']
    },
    'status': {
        'name': lazy_gettext('Status'),
        'meas': 'status',
        'units': ['enabled', 'bool', 'code', 'none']},
    'soil_moisture_cb': {
        'name': lazy_gettext('Soil Moisture'),
        'meas': 'soil_moisture',
        'units': ['cb', 'm3_m3']},
    'volumetric_water_content': {
        'name': lazy_gettext('토양 수분'),
        'meas': 'volumetric_water_content',
        'units': ['m3_m3', 'percent']},
    'clay': {
        'name': lazy_gettext('Clay Content'),
        'meas': 'clay',
        'units': ['percent']},
    'sand': {
        'name': lazy_gettext('Sand Content'),
        'meas': 'sand',
        'units': ['percent']},
    'silt': {
        'name': lazy_gettext('Silt Content'),
        'meas': 'silt',
        'units': ['percent']},
    'soc': {
        'name': lazy_gettext('Soil Organic Carbon'),
        'meas': 'soc',
        'units': ['dg_kg']},
    'bdod': {
        'name': lazy_gettext('Bulk Density'),
        'meas': 'bdod',
        'units': ['cg_cm3']},
    'ndvi': {
        'name': lazy_gettext('Vegetation Index (NDVI)'),
        'meas': 'ndvi',
        'units': ['none']}
}

# Measurement units
UNITS = {
    'unitless': {  # TODO: This unit and "none" are redundant. remove one.
        'name': lazy_gettext('Unitless'),
        'unit': ''},
    'us': {
        'name': lazy_gettext('Microsecond'),
        'unit': 'µs'},
    'uS_cm': {
        'name': lazy_gettext('Microsiemens per centimeter'),
        'unit': 'μS/cm'},
    'uSv_hr': {
        'name': lazy_gettext('Microsieverts per hour'),
        'unit': 'μSv/hr'},
    'A': {
        'name': lazy_gettext('Amp'),
        'unit': 'A'},
    'bar': {
        'name': lazy_gettext('Bar'),
        'unit': 'bar'},        
    'bearing': {
        'name': lazy_gettext('Bearing'),
        'unit': 'bearing'},
    'bool': {
        'name': lazy_gettext('Boolean'),
        'unit': 'bool'},
    'C': {
        'name': lazy_gettext('Celsius'),
        'unit': '°C'},
    'cb': {
        'name': lazy_gettext('Centibar'),
        'unit': 'cb'},
    'cie': {
        'name': lazy_gettext('CIE'),
        'unit': 'cie'},
    'cm': {
        'name': lazy_gettext('Centimeter'),
        'unit': 'cm'},
    'cm_water': {
        'name': lazy_gettext('Centimeters of water'),
        'unit': 'cm_water'},
    'code': {
        'name': lazy_gettext('Code'),
        'unit': 'none'},
    'cpm': {
        'name': lazy_gettext('Counts per minute'),
        'unit': 'cpm'},
    'cpu_load': {
        'name': lazy_gettext('CPU Load'),
        'unit': 'Proc.'},
    'day': {
        'name': lazy_gettext('Day'),
        'unit': 'day'},
    'dB': {
        'name': lazy_gettext('Decibel'),
        'unit': 'dB'},
    'dBm': {
        'name': lazy_gettext('Decibel-milliwatts'),
        'unit': 'dBm'},
    'decimal': {
        'name': lazy_gettext('Decimal'),
        'unit': ''},
    'degree': {
        'name': lazy_gettext('Degree'),
        'unit': '°'},
    'dS_m': {
        'name': lazy_gettext('Decisiemens per meter'),
        'unit': 'dS/m'},
    'eight_bit_color': {
        'name': lazy_gettext('8-Bit Color'),
        'unit': '8-bit'},
    'enabled': {
        'name': lazy_gettext('Enabled'),
        'unit': 'enabled'},
    'F': {
        'name': lazy_gettext('Fahrenheit'),
        'unit': '°F'},
    'ft': {
        'name': lazy_gettext('Foot'),
        'unit': 'ft'},
    'full': {
        'name': lazy_gettext('Full'),
        'unit': 'full'},
    'g_force': {
        'name': lazy_gettext('G-Force'),
        'unit': 'g'},
    'GB': {
        'name': lazy_gettext('Gigabyte'),
        'unit': 'GB'},
    'h': {
        'name': lazy_gettext('Hour'),
        'unit': 'h'},
    'hPa': {
        'name': lazy_gettext('Hectopascals'),
        'unit': 'hPa'},
    'Hz': {
        'name': lazy_gettext('Hertz'),
        'unit': 'Hz'},
    'ir': {
        'name': lazy_gettext('Infrared'),
        'unit': 'IR'},
    'inHg': {
        'name': lazy_gettext('Inches of mercury'),
        'unit': 'inHg'},
    'in': {
        'name': lazy_gettext('Inch'),
        'unit': 'in'},
    'in_h': {
        'name': lazy_gettext('Inches per hour'),
        'unit': 'in/h'},
    'index': {
        'name': lazy_gettext('Index'),
        'unit': 'index'},
    'K': {
        'name': lazy_gettext('Kelvin'),
        'unit': '°K'},
    'kB': {
        'name': lazy_gettext('Kilobyte'),
        'unit': 'kB'},
    'kgf_cm2': {
        'name': lazy_gettext('Kilogram-force per square centimeter'),
        'unit': 'kgf/cm²'},
    'kg_kg': {
        'name': lazy_gettext('Kilogram per kilogram'),
        'unit': 'kg/kg'},
    'kHz': {
        'name': lazy_gettext('Kilohertz'),
        'unit': 'kHz'},
    'kJ_kg': {
        'name': lazy_gettext('Kilojoule per kilogram'),
        'unit': 'kJ/kg'},
    'km': {
        'name': lazy_gettext('Kilometer'),
        'unit': 'km'},
    'kn': {
        'name': lazy_gettext('Knot'),
        'unit': 'knot'},
    'kPa': {
        'name': lazy_gettext('Kilopascal'),
        'unit': 'kPa'},
    'kWh': {
        'name': lazy_gettext('Kilowatt-hour'),
        'unit': 'kWh'},
    'l': {
        'name': lazy_gettext('Liter'),
        'unit': 'l'},
    'l_hr': {
        'name': lazy_gettext('Liters per Hour'),
        'unit': 'l/hr'},
    'l_min': {
        'name': lazy_gettext('Liters per Minute'),
        'unit': 'l/min'},
    'l_s': {
        'name': lazy_gettext('Liters Per Second'),
        'unit': 'l/s'},
    'lux': {
        'name': lazy_gettext('Lux'),
        'unit': 'lx'},
    'klux': {
        'name': lazy_gettext('Kilolux'),
        'unit': 'Klx'},
    'm': {
        'name': lazy_gettext('Meter'),
        'unit': 'm'},
    'm_s': {
        'name': lazy_gettext('Meters per second'),
        'unit': 'm/s'},
    'm_s_s': {
        'name': lazy_gettext('Meters per second per second'),
        'unit': 'm/s/s'},
    'mg_L': {
        'name': lazy_gettext('Milligram per Liter'),
        'unit': 'mg/L'},
    'minute': {
        'name': lazy_gettext('Minute'),
        'unit': 'min'},
    'mA': {
        'name': lazy_gettext('Milliamp'),
        'unit': 'mA'},
    'ml': {
        'name': lazy_gettext('Milliliter'),
        'unit': 'ml'},
    'mm': {
        'name': lazy_gettext('Millimeter'),
        'unit': 'mm'},
    'mm_h': {
        'name': lazy_gettext('Millimeters per hour'),
        'unit': 'mm/h'},
    'mph': {
        'name': lazy_gettext('Miles per hour'),
        'unit': 'mph'},
    'mV': {
        'name': lazy_gettext('Millivolt'),
        'unit': 'mV'},
    'm3_kg': {
        'name': lazy_gettext('Cubic meters per kilogram'),
        'unit': 'm^3/kg'},
    'MHz': {
        'name': lazy_gettext('Megahertz'),
        'unit': 'MHz'},
    'MB': {
        'name': lazy_gettext('Megabyte'),
        'unit': 'MB'},
    'none': {
        'name': lazy_gettext('Unitless'),
        'unit': ''},
    'Ohm': {
        'name': lazy_gettext('Ohm'),
        'unit': 'Ω'},
    'Pa': {
        'name': lazy_gettext('Pascal'),
        'unit': 'Pa'},
    'percent': {
        'name': lazy_gettext('Percent'),
        'unit': '%'},
    'pH': {
        'name': lazy_gettext('Ion Concentration'),
        'unit': 'pH'},
    'pid_value': {
        'name': lazy_gettext('PID values'),
        'unit': ''},
    'ppb': {
        'name': lazy_gettext('Parts per billion'),
        'unit': 'ppb'},
    'ppm': {
        'name': lazy_gettext('Parts per million'),
        'unit': 'ppm'},
    'ppt': {
        'name': lazy_gettext('Parts per thousand'),
        'unit': 'ppt'},
    'psi': {
        'name': lazy_gettext('Pounds per square inch'),
        'unit': 'psi'},
    'rpm': {
        'name': lazy_gettext('Revolutions per minute'),
        'unit': 'rpm'},
    's': {
        'name': lazy_gettext('Second'),
        'unit': 's'},
    'setpoint': {
        'name': lazy_gettext('Setpoint'),
        'unit': ''},
    'steps': {
        'name': lazy_gettext('Steps'),
        'unit': 'steps'},
    'ug_m3': {
        'name': lazy_gettext('Microgram per cubic meter'),
        'unit': 'μg/m^3'},
    'uT': {
        'name': lazy_gettext('Microtesla'),
        'unit': 'μT'},
    'va': {
        'name': 'Volt-Amps',
        'unit': 'VA'},
    'var': {
        'name': 'Volt-Amps-Reactive',
        'unit': 'VAr'},
    'V': {
        'name': lazy_gettext('Volt'),
        'unit': 'V'},
    'W': {
        'name': lazy_gettext('Watt'),
        'unit': 'W'},
    'W_m2': {
        'name': lazy_gettext('Watts per square meter'),
        'unit': 'W/m²'
    },
    'J_cm2': {
        'name': lazy_gettext('Joules per square centimeter'),
        'unit': 'J/cm²'},
    'umol_m2_s': {
        'name': lazy_gettext('Micromoles per square meter per second'),
        'unit': 'µmol·m⁻²·s⁻¹'},
    'dg_kg': {
        'name': lazy_gettext('Decigram per kilogram'),
        'unit': 'dg/kg'},
    'cg_cm3': {
        'name': lazy_gettext('Centigram per cubic centimeter'),
        'unit': 'cg/cm³'},
    'm3_m3': {
        'name': lazy_gettext('Volumetric Water Content'),
        'unit': 'm³/m³'}
}

# Initial conversions
# These are added to the SQLite database when it's created
# Users may add or delete after that
UNIT_CONVERSIONS = [
    # Speed
    ('m_s', 'mph', 'x*2.2369362920544'),
    ('m_s', 'kn', 'x*1.9438444924406'),
    ('mph', 'm_s', 'x/2.2369362920544'),
    ('mph', 'kn', 'x/1.1507794480235'),
    ('kn', 'm_s', 'x/1.9438444924406'),
    ('kn', 'mph', 'x*1.1507794480235'),

    # Acceleration
    ('g_force', 'm_s_s', 'x*9.80665'),
    ('m_s_s', 'g_force', 'x/9.80665'),

    # Temperature
    ('C', 'F', 'x*(9/5)+32'),
    ('C', 'K', 'x+273.15'),
    ('F', 'C', '(x-32)*5/9'),
    ('F', 'K', '(x+459.67)*5/9'),
    ('K', 'C', 'x-273.15'),
    ('K', 'F', '(x*9/5)−459.67'),

    # Frequency
    ('Hz', 'kHz', 'x/1000'),
    ('Hz', 'MHz', 'x/1000000'),
    ('kHz', 'Hz', 'x*1000'),
    ('kHz', 'MHz', 'x/1000'),
    ('MHz', 'Hz', 'x*1000000'),
    ('MHz', 'kHz', 'x*1000'),

    # Length
    ('ft', 'm', 'x/3.2808399'),
    ('m', 'ft', 'x*3.2808399'),
    ('m', 'cm', 'x*100'),
    ('m', 'mm', 'x*1000'),
    ('mm', 'cm', 'x/10'),
    ('mm', 'm', 'x/1000'),
    ('cm', 'mm', 'x*10'),
    ('cm', 'm', 'x/100'),
    ('km', 'm', 'x*1000'),
    ('m', 'km', 'x/1000'),
    ('in', 'cm', 'x*2.54'),
    ('cm', 'in', 'x/2.54'),
    ('in', 'mm', 'x*25.4'),
    ('mm', 'in', 'x/25.4'),
    ('in', 'm', 'x*0.0254'),
    ('m', 'in', 'x/0.0254'),
    ('ft', 'in', 'x*12'),
    ('in', 'ft', 'x/12'),

    # Disk size
    ('kB', 'MB', 'x/1000'),
    ('kB', 'GB', 'x/1000000'),
    ('MB', 'kB', 'x*1000'),
    ('MB', 'GB', 'x/1000'),
    ('GB', 'kB', 'x*1000000'),
    ('GB', 'MB', 'X*1000'),

    # Concentration
    ('ppt', 'ppm', 'x*1000'),
    ('ppt', 'ppb', 'x*1000000'),
    ('ppm', 'ppt', 'x/1000'),
    ('ppm', 'ppb', 'x*1000'),
    ('ppb', 'ppt', 'x/1000000'),
    ('ppb', 'ppm', 'x/1000'),
    ('ppt', 'percent', 'x/10'),
    ('ppm', 'percent', 'x/10000'),
    ('ppb', 'percent', 'x/10000000'),
    ('percent', 'ppt', 'x*10'),
    ('percent', 'ppm', 'x*10000'),
    ('percent', 'ppb', 'x*10000000'),

    # Electrical conductivity
    ('uS_cm', 'dS_m', 'x/1000'),
    ('dS_m', 'uS_cm', 'x*1000'),

    # Number
    ('percent', 'decimal', 'x/100'),
    ('decimal', 'percent', 'x*100'),

    # Pressure
    ('Pa', 'bar', 'x/100000'),
    ('bar', 'Pa', 'x*100000'),
    ('kPa', 'bar', 'x/100'),
    ('bar', 'kPa', 'x*100'),
    ('hPa', 'bar', 'x/1000'),
    ('bar', 'hPa', 'x*1000'),
    ('psi', 'bar', 'x/14.5037738'),
    ('bar', 'psi', 'x*14.5037738'),
    ('Pa', 'kPa', 'x/1000'),
    ('Pa', 'hPa', 'x/100'),
    ('hPa', 'Pa', 'x*100'),
    ('hPa', 'kPa', 'x/10'),
    ('kPa', 'Pa', 'x*1000'),
    ('kPa', 'hPa', 'x*10'),
    ('psi', 'cm_water', 'x*70.306957964239'),
    ('psi', 'kPa', 'x*6.8947572932'),
    ('kPa', 'psi', 'x/6.8947572932'),
    ('hPa', 'kgf_cm2', 'x/980.665'),
    ('kgf_cm2', 'hPa', 'x*980.665'),
    # Inches of mercury
    ('inHg', 'hPa', 'x*33.8639'),
    ('hPa', 'inHg', 'x/33.8639'),

    # precipitation
    ('in_h', 'mm_h', 'x*25.4'),
    ('mm_h', 'in_h', 'x/25.4'),

    # Rate - Volume
    ('l_s', 'l_min', 'x*60'),
    ('l_s', 'l_hr', 'x*60*60'),
    ('l_min', 'l_s', 'x/60'),
    ('l_min', 'l_hr', 'x*60'),
    ('l_hr', 'l_s', 'x/60/60'),
    ('l_hr', 'l_min', 'x/60'),

    # Time
    ('s', 'minute', 'x/60'),
    ('s', 'h', 'x/60/60'),
    ('s', 'day', 'x/60/60/24'),
    ('minute', 's', 'x*60'),
    ('minute', 'h', 'x/60'),
    ('minute', 'day', 'x/60/24'),
    ('h', 's', 'x*60*60'),
    ('h', 'minute', 'x*60'),
    ('h', 'day', 'x*60*24'),
    ('day', 's', 'x*60*60*24'),
    ('day', 'minute', 'x*60*24'),
    ('day', 'h', 'x*24'),

    # Volt
    ('V', 'mV', 'x*1000'),
    ('mV', 'V', 'x/1000'),

    # Electrical Current
    ('A', 'mA', 'x*1000'),
    ('mA', 'A', 'x/1000'),

    # Volume
    ('l', 'ml', 'x*1000'),
    ('ml', 'l', 'x/1000'),

    # Light
    ('lux', 'full', 'x*1000'),
    ('full', 'lux', 'x/1000'),


    # Klux conversions
    ('klux', 'lux', 'x * 1000'),
    ('lux', 'klux', 'x / 1000'),
    # Klux <-> W/m²
    ('klux', 'W_m2', 'x * 7.9'),
    ('W_m2', 'klux', 'x / 7.9'),
    # Lux <-> W/m²
    ('lux', 'W_m2', 'x * 0.0079'),
    ('W_m2', 'lux', 'x / 0.0079'),
    
    # Solar Radiation
    ('J_cm2', 'W_m2', 'x * 10000'),    # 1 J/cm² = 10000 W/m²
    ('W_m2', 'J_cm2', 'x / 10000'),    # 1 W/m² = 0.0001 J/cm²

    # Soil moisture: cb <-> kPa (1 cb = 1 kPa)
    ('cb', 'kPa', 'x'),
    ('kPa', 'cb', 'x'),

    # W_m2 <-> umol_m2_s (대략적 변환: 1 W/m² ≈ 4.57 µmol·m⁻²·s⁻¹)
    ('W_m2', 'umol_m2_s', 'x * 4.57'),
    ('umol_m2_s', 'W_m2', 'x / 4.57'),

    # J/cm² <-> umol_m2_s (1 J/cm² ≈ 45700 µmol·m⁻²·s⁻¹, 1초 집적 시간 가정)
    ('J_cm2', 'umol_m2_s', 'x * 45700'),
    ('umol_m2_s', 'J_cm2', 'x / 45700')

]


def add_measurement_unit(meas_key, unit_key, meas_name=None, unit_name=None):
    """Dynamically adds a measurement or unit if it doesn't exist."""
    if meas_key not in MEASUREMENTS:
        MEASUREMENTS[meas_key] = {
            'name': meas_name if meas_name else meas_key.replace('_', ' ').capitalize(),
            'meas': meas_key,
            'units': [unit_key]
        }
    elif unit_key not in MEASUREMENTS[meas_key]['units']:
        MEASUREMENTS[meas_key]['units'].append(unit_key)

    if unit_key not in UNITS:
        UNITS[unit_key] = {
            'name': unit_name if unit_name else unit_key,
            'unit': unit_key
        }
