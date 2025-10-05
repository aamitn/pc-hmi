# -----------------------------------------------------------------------------
# Instructions:
# 1. Install the required external libraries:
#    pip install screeninfo PyQt6 psutil wmi py-cpuinfo pynvml GPUtil pyamdgpuinfo
#    (Note: 'wmi' is Windows-specific. 'pynvml' is NVIDIA-specific.)
#    For AMD on Windows, also consider: pip install pyadl
# 2. Run the script:
#    python hmi.py
#
# This script implements a fully-featured System Monitoring and Control Dashboard 
# with support for NVIDIA, AMD, Intel, and other GPUs using multiple detection methods.
# -----------------------------------------------------------------------------

import sys
import random
import time
import psutil 
import platform 
import subprocess
import multiprocessing
import re
import json
import configparser
import os

# --- GPU DETECTION LIBRARIES ---
try:
    import wmi
except ImportError:
    wmi = None

try:
    import cpuinfo
except ImportError:
    cpuinfo = None

# NVIDIA GPU Support (pynvml)
try:
    from pynvml import nvmlInit, nvmlShutdown, nvmlDeviceGetCount, nvmlDeviceGetHandleByIndex, nvmlDeviceGetName, \
                        nvmlDeviceGetUtilizationRates, nvmlDeviceGetTemperature, nvmlDeviceGetMemoryInfo, \
                        nvmlDeviceGetPowerUsage, nvmlDeviceGetClockInfo, nvmlSystemGetDriverVersion, NVMLError, nvmlConstants as NVM
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False
    print("INFO: pynvml not found. NVIDIA GPU stats via NVML will be unavailable.")

# GPUtil for cross-platform GPU detection
try:
    import GPUtil
    GPUTIL_AVAILABLE = True
except ImportError:
    GPUTIL_AVAILABLE = False
    print("INFO: GPUtil not found. Fallback GPU detection will be limited.")

# AMD GPU Support (pyamdgpuinfo for Linux)
try:
    import pyamdgpuinfo
    PYAMDGPUINFO_AVAILABLE = True
except ImportError:
    PYAMDGPUINFO_AVAILABLE = False
    print("INFO: pyamdgpuinfo not found. AMD GPU monitoring on Linux will be unavailable.")

# AMD GPU Support (pyadl for Windows)
try:
    from pyadl import ADLManager
    PYADL_AVAILABLE = True
except ImportError:
    PYADL_AVAILABLE = False
    print("INFO: pyadl not found. AMD GPU monitoring on Windows will be limited.")

# ----------------------------------
# PyQt6 
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QMessageBox, QListWidget, QStackedWidget, 
    QGridLayout, QPushButton, QTableWidget, QTableWidgetItem, 
    QHeaderView, QSizePolicy, QGroupBox, QScrollArea, QDialog
)
from PyQt6.QtCore import Qt, QPoint, QTimer, QSize, QRectF, QThread, pyqtSignal, QUrl, QByteArray, QLocale, QDate, QTime, QSize, QRect, QBuffer, QIODevice
from PyQt6.QtGui import QIcon, QFont, QScreen, QPainter, QPen, QColor, QBrush, QConicalGradient, QMovie
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply # Networking imports for GIF fetching

from screeninfo import get_monitors
import getpass

def load_settings():
    """
    Load settings from settings.ini file in the script's directory.
    Returns a dictionary with 'giphy_api_key' and 'config_resolution'.
    """
    settings = {
        'giphy_api_key': "YOUR_API_KEY",  # Default GIPHY key
        'config_resolution': None  # Default to None (auto-detect smallest monitor)
    }
    
    # Get the directory where the script is running
    script_dir = os.path.dirname(os.path.abspath(__file__))
    settings_path = os.path.join(script_dir, 'settings.ini')
    
    # Check if settings.ini exists
    if not os.path.exists(settings_path):
        print(f"INFO: settings.ini not found at {settings_path}")
        print("INFO: Using default settings. Creating sample settings.ini...")
        create_sample_settings(settings_path)
        return settings
    
    try:
        config = configparser.ConfigParser()
        config.read(settings_path)
        
        # Read GIPHY API Key
        if config.has_option('API', 'giphy_api_key'):
            api_key = config.get('API', 'giphy_api_key').strip()
            if api_key:
                settings['giphy_api_key'] = api_key
                print(f"INFO: Loaded GIPHY API key from settings.ini")
        
        # Read config_resolution
        if config.has_option('Display', 'resolution'):
            resolution = config.get('Display', 'resolution').strip()
            if resolution:
                settings['config_resolution'] = resolution
                print(f"INFO: Loaded target resolution from settings.ini: {resolution}")
        
    except Exception as e:
        print(f"WARNING: Error reading settings.ini: {e}")
        print("INFO: Using default settings")
    
    return settings


def create_sample_settings(settings_path):
    """Create a sample settings.ini file with default values."""
    try:
        config = configparser.ConfigParser()
        
        config['API'] = {
            'giphy_api_key': 'YOUR_API_KEY'
        }
        
        config['Display'] = {
            'resolution': '# Examples: 1920x1080, 1280x720, 800x600',
            '# Leave empty or comment out to auto-detect smallest monitor': ''
        }
        
        with open(settings_path, 'w') as configfile:
            configfile.write("# System Dashboard Settings\n")
            configfile.write("# Edit these values to customize your dashboard\n\n")
            config.write(configfile)
        
        print(f"INFO: Created sample settings.ini at {settings_path}")
    except Exception as e:
        print(f"WARNING: Could not create sample settings.ini: {e}")
        
        
# --- GPU Detection Class ---

class GPUDetector:
    """
    Universal GPU detector that supports NVIDIA, AMD, Intel, and other GPUs
    using multiple detection methods with live monitoring support.
    """
    def __init__(self):
        self.gpu_type = "Unknown"
        self.gpu_name = "No GPU Detected"
        self.gpu_memory = 0
        self.driver_version = "N/A"
        self.can_monitor = False
        self.nvml_handle = None
        self.amd_device = None
        self.amd_manager = None
        
        self._detect_gpu()
    
    def _detect_gpu(self):
        """Try multiple detection methods in order of preference."""
        
        # Method 1: Try NVIDIA NVML first (most detailed for NVIDIA)
        if NVML_AVAILABLE and self._try_nvidia_nvml():
            return
        
        # Method 2: Try AMD-specific libraries
        if self._try_amd_monitoring():
            return
        
        # Method 3: Try GPUtil (cross-platform, works for NVIDIA and some AMD)
        if GPUTIL_AVAILABLE and self._try_gputil():
            return
        
        # Method 4: Try WMI on Windows (works for all GPU types)
        if wmi and platform.system() == 'Windows' and self._try_wmi():
            return
        
        # Method 5: Try OpenCL/system commands (Linux/Mac fallback)
        if self._try_system_detection():
            return
        
        print("WARNING: No GPU detected or all detection methods failed.")
    
    def _try_nvidia_nvml(self):
        """Attempt to detect NVIDIA GPU using NVML."""
        try:
            nvmlInit()
            if nvmlDeviceGetCount() > 0:
                self.nvml_handle = nvmlDeviceGetHandleByIndex(0)
                self.gpu_name = nvmlDeviceGetName(self.nvml_handle).decode('utf-8')
                self.gpu_type = "NVIDIA"
                
                mem = nvmlDeviceGetMemoryInfo(self.nvml_handle)
                self.gpu_memory = round(mem.total / (1024**3), 1)
                
                self.driver_version = nvmlSystemGetDriverVersion().decode('utf-8')
                self.can_monitor = True
                
                print(f"SUCCESS: Detected NVIDIA GPU via NVML: {self.gpu_name}")
                return True
        except Exception as e:
            print(f"NVML detection failed: {e}")
            if NVML_AVAILABLE:
                try:
                    nvmlShutdown()
                except:
                    pass
        return False
    
    def _try_amd_monitoring(self):
        """Attempt to detect and enable AMD GPU monitoring."""
        
        # Try pyamdgpuinfo (Linux)
        if PYAMDGPUINFO_AVAILABLE and platform.system() == 'Linux':
            try:
                pyamdgpuinfo.detect_gpus()
                num_gpus = pyamdgpuinfo.get_gpu_count()
                
                if num_gpus > 0:
                    self.amd_device = pyamdgpuinfo.get_gpu(0)
                    self.gpu_name = self.amd_device.name
                    self.gpu_type = "AMD"
                    
                    # Get memory info
                    try:
                        vram_size = self.amd_device.query_vram_size()
                        self.gpu_memory = round(vram_size / (1024**3), 1)
                    except:
                        self.gpu_memory = 0
                    
                    # Try to get driver version
                    try:
                        self.driver_version = self.amd_device.query_driver_version()
                    except:
                        self.driver_version = "N/A"
                    
                    self.can_monitor = True
                    print(f"SUCCESS: Detected AMD GPU via pyamdgpuinfo: {self.gpu_name}")
                    return True
            except Exception as e:
                print(f"pyamdgpuinfo detection failed: {e}")
        
        # Try pyadl (Windows)
        if PYADL_AVAILABLE and platform.system() == 'Windows':
            try:
                self.amd_manager = ADLManager.getInstance()
                devices = self.amd_manager.getDevices()
                
                if devices:
                    device = devices[0]
                    self.gpu_name = device.adapterName
                    self.gpu_type = "AMD"
                    
                    # Get memory info (in MB, convert to GB)
                    try:
                        mem_info = device.getCurrentMemoryInfo()
                        self.gpu_memory = round(mem_info['total'] / 1024, 1)
                    except:
                        self.gpu_memory = 0
                    
                    # Try to get driver version
                    try:
                        self.driver_version = device.driverVersion
                    except:
                        self.driver_version = "N/A"
                    
                    self.can_monitor = True
                    print(f"SUCCESS: Detected AMD GPU via pyadl: {self.gpu_name}")
                    return True
            except Exception as e:
                print(f"pyadl detection failed: {e}")
        
        return False
    
    def _try_gputil(self):
        """Attempt to detect GPU using GPUtil."""
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                gpu = gpus[0]
                self.gpu_name = gpu.name
                self.gpu_memory = round(gpu.memoryTotal / 1024, 1)  # Convert MB to GB
                self.driver_version = gpu.driver if hasattr(gpu, 'driver') else "N/A"
                
                # Determine vendor
                if 'nvidia' in self.gpu_name.lower():
                    self.gpu_type = "NVIDIA"
                elif 'amd' in self.gpu_name.lower() or 'radeon' in self.gpu_name.lower():
                    self.gpu_type = "AMD"
                elif 'intel' in self.gpu_name.lower():
                    self.gpu_type = "Intel"
                else:
                    self.gpu_type = "Generic"
                
                self.can_monitor = True
                print(f"SUCCESS: Detected GPU via GPUtil: {self.gpu_name} ({self.gpu_type})")
                return True
        except Exception as e:
            print(f"GPUtil detection failed: {e}")
        return False
    
    def _try_wmi(self):
        """Attempt to detect GPU using WMI (Windows only)."""
        try:
            c = wmi.WMI()
            gpus = c.Win32_VideoController()
            
            if gpus:
                gpu = gpus[0]
                self.gpu_name = gpu.Name
                
                # Try to get memory (in bytes, convert to GB)
                if hasattr(gpu, 'AdapterRAM') and gpu.AdapterRAM:
                    self.gpu_memory = round(int(gpu.AdapterRAM) / (1024**3), 1)
                
                # Get driver version
                if hasattr(gpu, 'DriverVersion'):
                    self.driver_version = gpu.DriverVersion
                
                # Determine vendor
                name_lower = self.gpu_name.lower()
                if 'nvidia' in name_lower or 'geforce' in name_lower or 'quadro' in name_lower:
                    self.gpu_type = "NVIDIA"
                elif 'amd' in name_lower or 'radeon' in name_lower:
                    self.gpu_type = "AMD"
                elif 'intel' in name_lower:
                    self.gpu_type = "Intel"
                else:
                    self.gpu_type = "Generic"
                
                self.can_monitor = False  # WMI doesn't provide real-time monitoring
                print(f"SUCCESS: Detected GPU via WMI: {self.gpu_name} ({self.gpu_type})")
                return True
        except Exception as e:
            print(f"WMI GPU detection failed: {e}")
        return False
    
    def _try_system_detection(self):
        """Try system-specific commands to detect GPU."""
        try:
            # Linux: Try lspci
            if platform.system() == 'Linux':
                result = subprocess.run(['lspci'], capture_output=True, text=True)
                for line in result.stdout.split('\n'):
                    if 'VGA' in line or '3D' in line:
                        self.gpu_name = line.split(':')[-1].strip()
                        
                        name_lower = self.gpu_name.lower()
                        if 'nvidia' in name_lower:
                            self.gpu_type = "NVIDIA"
                        elif 'amd' in name_lower or 'radeon' in name_lower:
                            self.gpu_type = "AMD"
                        elif 'intel' in name_lower:
                            self.gpu_type = "Intel"
                        else:
                            self.gpu_type = "Generic"
                        
                        print(f"SUCCESS: Detected GPU via lspci: {self.gpu_name} ({self.gpu_type})")
                        return True
            
            # macOS: Try system_profiler
            elif platform.system() == 'Darwin':
                result = subprocess.run(['system_profiler', 'SPDisplaysDataType'], 
                                      capture_output=True, text=True)
                match = re.search(r'Chipset Model: (.+)', result.stdout)
                if match:
                    self.gpu_name = match.group(1).strip()
                    
                    name_lower = self.gpu_name.lower()
                    if 'nvidia' in name_lower:
                        self.gpu_type = "NVIDIA"
                    elif 'amd' in name_lower or 'radeon' in name_lower:
                        self.gpu_type = "AMD"
                    elif 'intel' in name_lower or 'apple' in name_lower:
                        self.gpu_type = "Intel/Apple"
                    else:
                        self.gpu_type = "Generic"
                    
                    print(f"SUCCESS: Detected GPU via system_profiler: {self.gpu_name} ({self.gpu_type})")
                    return True
        except Exception as e:
            print(f"System command GPU detection failed: {e}")
        
        return False
    
    def get_live_stats(self):
        """
        Get live GPU statistics if monitoring is available.
        Returns dict with: load, temp, vram_used, vram_total, core_clock, mem_clock, power
        """
        stats = {
            'load': 0,
            'temp': 0,
            'vram_used': 0,
            'vram_total': self.gpu_memory * 1024,  # Convert GB to MB
            'core_clock': 0,
            'mem_clock': 0,
            'power': 0
        }
        
        if not self.can_monitor:
            return stats
        
        # NVIDIA NVML monitoring
        if self.gpu_type == "NVIDIA" and self.nvml_handle:
            try:
                util = nvmlDeviceGetUtilizationRates(self.nvml_handle)
                stats['load'] = util.gpu
                
                stats['temp'] = nvmlDeviceGetTemperature(self.nvml_handle, NVM.NVML_TEMP_GPU)
                
                mem = nvmlDeviceGetMemoryInfo(self.nvml_handle)
                stats['vram_used'] = mem.used // (1024**2)
                stats['vram_total'] = mem.total // (1024**2)
                
                try:
                    stats['power'] = nvmlDeviceGetPowerUsage(self.nvml_handle) / 1000
                except:
                    stats['power'] = 0
                
                stats['core_clock'] = nvmlDeviceGetClockInfo(self.nvml_handle, NVM.NVML_CLOCK_GRAPHICS, NVM.NVML_CLOCK_ID_CURRENT)
                stats['mem_clock'] = nvmlDeviceGetClockInfo(self.nvml_handle, NVM.NVML_CLOCK_MEM, NVM.NVML_CLOCK_ID_CURRENT)
                
            except Exception as e:
                print(f"Error fetching NVIDIA stats: {e}")
        
        # AMD pyamdgpuinfo monitoring (Linux)
        elif self.gpu_type == "AMD" and self.amd_device and PYAMDGPUINFO_AVAILABLE:
            try:
                # GPU Load
                stats['load'] = self.amd_device.query_load() * 100
                
                # Temperature
                stats['temp'] = self.amd_device.query_temperature()
                
                # VRAM usage
                vram_used = self.amd_device.query_vram_used()
                vram_total = self.amd_device.query_vram_size()
                stats['vram_used'] = vram_used // (1024**2)
                stats['vram_total'] = vram_total // (1024**2)
                
                # Clock speeds
                try:
                    stats['core_clock'] = self.amd_device.query_sclk()
                    stats['mem_clock'] = self.amd_device.query_mclk()
                except:
                    pass
                
                # Power draw
                try:
                    stats['power'] = self.amd_device.query_power() / 1000000  # Convert from uW to W
                except:
                    pass
                
            except Exception as e:
                print(f"Error fetching AMD stats (pyamdgpuinfo): {e}")
        
        # AMD pyadl monitoring (Windows)
        elif self.gpu_type == "AMD" and self.amd_manager and PYADL_AVAILABLE:
            try:
                devices = self.amd_manager.getDevices()
                if devices:
                    device = devices[0]
                    
                    # GPU Load
                    try:
                        stats['load'] = device.getCurrentUsage()
                    except:
                        pass
                    
                    # Temperature
                    try:
                        stats['temp'] = device.getCurrentTemperature()
                    except:
                        pass
                    
                    # VRAM usage
                    try:
                        mem_info = device.getCurrentMemoryInfo()
                        stats['vram_used'] = mem_info['used']
                        stats['vram_total'] = mem_info['total']
                    except:
                        pass
                    
                    # Clock speeds
                    try:
                        core_clock = device.getCurrentCoreClock()
                        mem_clock = device.getCurrentMemoryClock()
                        stats['core_clock'] = core_clock
                        stats['mem_clock'] = mem_clock
                    except:
                        pass
                
            except Exception as e:
                print(f"Error fetching AMD stats (pyadl): {e}")
        
        # GPUtil monitoring (works for NVIDIA and some AMD)
        elif GPUTIL_AVAILABLE:
            try:
                gpus = GPUtil.getGPUs()
                if gpus:
                    gpu = gpus[0]
                    stats['load'] = gpu.load * 100
                    stats['temp'] = gpu.temperature
                    stats['vram_used'] = gpu.memoryUsed
                    stats['vram_total'] = gpu.memoryTotal
            except Exception as e:
                print(f"Error fetching GPUtil stats: {e}")
        
        return stats

# Initialize GPU detector
gpu_detector = GPUDetector()

# --- Helper Functions (Monitor Detection) ---

def find_target_monitor(resolution_str=None):
    """
    Finds the target monitor based on a configured resolution or falls back 
    to the smallest monitor area.
    """
    print("--- 1. Detecting connected displays...")
    try:
        monitors = get_monitors()
    except Exception as e:
        print(f"Error detecting monitors: {e}")
        return None

    if not monitors:
        print("No monitors detected.")
        return None

    if resolution_str:
        try:
            target_width, target_height = map(int, resolution_str.lower().split('x'))
            for monitor in monitors:
                if monitor.width == target_width and monitor.height == target_height:
                    print(f"MATCH: Found configured resolution {resolution_str} at ({monitor.x}, {monitor.y}).")
                    return monitor
            print(f"WARNING: Configured resolution '{resolution_str}' not found. Falling back to smallest monitor.")
        except ValueError:
            print(f"WARNING: Configuration resolution format '{resolution_str}' is invalid. Falling back to smallest monitor.")

    # Fallback to finding smallest area
    smallest_area = float('inf')
    target_monitor = None
    
    for monitor in monitors:
        area = monitor.width * monitor.height
        if area < smallest_area:
            smallest_area = area
            target_monitor = monitor
            
    if target_monitor:
        print(f"FALLBACK: Targeting smallest screen: {target_monitor.width}x{target_monitor.height} (Area: {smallest_area:,}).")
    return target_monitor

# --- Icon Map (Using basic text/symbols for lack of font-awesome) ---

ICON_MAP = {
    "dashboard": "📊",
    "cpu": "🧠",
    "ram": "💾",
    "disk": "💿",
    "net": "🌐",
    "gpu": "📺",
    "apps": "📦",
    "control": "⚙️",
    "globe": "🌍", # New icon for GIF tab
    "reload": "🔄",
    "fullscreen": "🖼️"
}

# --- Custom Circular Progress Widget ---

class CircularProgressBar(QWidget):
    """A custom widget to display progress in a circular gauge."""
    def __init__(self, title, start_color="#3498db", end_color="#2ecc71", parent=None):
        super().__init__(parent)
        self.value = 0
        self.title = title
        self.start_color = start_color
        self.end_color = end_color
        self.setMinimumSize(QSize(150, 150))
        self.setMaximumSize(QSize(250, 250)) 

    def setValue(self, value):
        """Sets the current percentage value (0-100)."""
        if 0 <= value <= 100:
            self.value = value
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect_f = self.rect().toRectF().adjusted(10, 10, -10, -10)
        center_f = rect_f.center() 
        radius = min(rect_f.width(), rect_f.height()) / 2.0
        
        # Draw the Background Track
        track_pen = QPen(QColor("#34495e"), 10)
        track_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track_pen)
        painter.drawEllipse(center_f, radius, radius) 
        
        # Draw the Progress Arc
        progress_pen = QPen(QColor(self.start_color), 10)
        progress_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        
        gradient = QConicalGradient(center_f, 90)
        gradient.setColorAt(0, QColor(self.start_color))
        gradient.setColorAt(1, QColor(self.end_color))
        progress_pen.setBrush(QBrush(gradient))
        
        painter.setPen(progress_pen)
        
        start_angle = 90 * 16
        span_angle = int(-self.value * 3.6 * 16)
        
        painter.drawArc(rect_f, start_angle, span_angle)

        # Draw Text in Center
        painter.setPen(QPen(QColor("#ecf0f1")))
        
        font_value = QFont("Inter", int(radius * 0.45), QFont.Weight.Bold)
        painter.setFont(font_value)
        value_text = f"{int(self.value)}%"
        painter.drawText(rect_f, Qt.AlignmentFlag.AlignCenter, value_text)
        
        font_title = QFont("Inter", int(radius * 0.15), QFont.Weight.DemiBold)
        painter.setFont(font_title)
        
        title_rect = QRectF(rect_f)
        title_rect.moveBottom(rect_f.bottom() + radius * 0.4) 
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignCenter, self.title)


class FullScreenGifDialog(QDialog):
    """A modal dialog to display a GIF in full screen on the current monitor."""
    def __init__(self, movie_data: QByteArray, parent=None):
        super().__init__(parent)
        
        self.movie_data = QByteArray(movie_data)  # Make a copy
        self.gif_buffer = None
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.gif_label = QLabel()
        self.gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gif_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.gif_label.setScaledContents(False)
        
        # Create buffer and movie
        self.gif_buffer = QBuffer(self.movie_data)
        if not self.gif_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
            self.gif_label.setText("Error loading GIF data for full screen.")
            self.layout.addWidget(self.gif_label)
            return

        self.movie = QMovie()
        self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self.movie.setDevice(self.gif_buffer)
        
        # Remove speed setting - let it play at original speed
        # self.movie.setSpeed(100)  # Remove this line
        
        self.gif_label.setMovie(self.movie)
        self.layout.addWidget(self.gif_label)
        
        # Close button
        self.close_button = QPushButton("✕ Close (Esc)")
        self.close_button.setFont(QFont("Inter", 12))
        self.close_button.setStyleSheet("""
            QPushButton { 
                background-color: rgba(44, 62, 80, 200); 
                color: #ecf0f1; 
                border-radius: 10px; 
                padding: 10px 20px;
            }
            QPushButton:hover { 
                background-color: rgba(52, 73, 94, 220); 
            }
        """)
        self.close_button.clicked.connect(self.close)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(self.close_button)
        btn_layout.addSpacing(20)
        self.layout.addLayout(btn_layout)
        
        # Start movie only after everything is set up
        QTimer.singleShot(100, self.movie.start)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)
        
    def closeEvent(self, event):
        if self.movie:
            self.movie.stop()
        if self.gif_buffer and self.gif_buffer.isOpen():
            self.gif_buffer.close()
        super().closeEvent(event)

# --- Content Pages ---

class BasePage(QWidget):
    """Base class for dashboard content pages with scrolling support."""
    def __init__(self, title):
        super().__init__()
        
        main_page_layout = QVBoxLayout(self)
        main_page_layout.setContentsMargins(0, 0, 0, 0) 

        self.content_widget = QWidget()
        self.layout = QVBoxLayout(self.content_widget)
        self.layout.setContentsMargins(30, 30, 30, 30)
        self.layout.setSpacing(20)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.content_widget)
        scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        main_page_layout.addWidget(scroll_area)
        
        title_label = QLabel(title)
        title_label.setFont(QFont("Inter", 28, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #ecf0f1;")
        self.layout.addWidget(title_label)
        self.layout.addSpacing(10)
        self.layout.addWidget(self._create_separator())
    
    def _create_separator(self, height=2, color="#34495e"):
        separator = QWidget()
        separator.setFixedHeight(height)
        separator.setStyleSheet(f"background-color: {color}; border: none;")
        return separator

    def _create_info_label(self, text):
            # Check if 'text' is bytes, and decode it if necessary.
            if isinstance(text, bytes):
                text = text.decode('utf-8')
                
            label = QLabel(text)
            label.setFont(QFont("Inter", 12))
            label.setStyleSheet("color: #ecf0f1;")
            return label

class GifPage(BasePage):
    """A content page to display a random GIF."""
    
    def __init__(self, parent=None):
        super().__init__("Random GIF Viewer")
        self.parent = parent
        
        # Use the API key passed from settings
        self.GIPHY_API_KEY = giphy_api_key
        self.GIPHY_RANDOM_URL = f"https://api.giphy.com/v1/gifs/random?api_key={self.GIPHY_API_KEY}&tag=computer,tech,cat,funny&rating=g"
        
        
        self.manager = QNetworkAccessManager()
        self.manager.finished.connect(self._handle_network_reply)
        
        self.current_gif_url = None
        self.current_gif_data = QByteArray()
        self.gif_buffer = None # Attribute to hold the QBuffer for the QMovie
        
        # --- UI Elements ---
        
        self.gif_label = QLabel("Click 'Load New GIF' to start.")
        self.gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gif_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.gif_label.setStyleSheet("color: #7f8c8d; border: 2px dashed #34495e; padding: 20px; min-height: 400px;")
        self.gif_label.setFont(QFont("Inter", 18))
        
        # Controls
        controls_layout = QHBoxLayout()
        
        self.load_button = self._create_button("Load New GIF", "reload", "#2ecc71")
        self.load_button.clicked.connect(self.load_random_gif)
        
        self.fullscreen_button = self._create_button("Full Screen", "fullscreen", "#e67e22")
        self.fullscreen_button.clicked.connect(self.show_fullscreen)
        self.fullscreen_button.setEnabled(False)
        
        controls_layout.addWidget(self.load_button)
        controls_layout.addWidget(self.fullscreen_button)
        controls_layout.addStretch(1)
        
        # Add to main layout
        self.layout.addLayout(controls_layout)
        self.layout.addWidget(self.gif_label)
        self.layout.addStretch(1)
        
        # Start loading a GIF immediately
        self.load_random_gif()

    def _create_button(self, text, icon_name, color):
        """Helper to create styled control buttons."""
        button = QPushButton(f"{ICON_MAP.get(icon_name, '')} {text}")
        button.setFont(QFont("Inter", 14, QFont.Weight.Bold))
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 12px 25px;
                margin: 5px;
            }}
            QPushButton:hover {{
                background-color: {QColor(color).lighter(120).name()};
            }}
            QPushButton:pressed {{
                background-color: {QColor(color).darker(120).name()};
                padding-top: 14px;
                padding-bottom: 10px;
            }}
            QPushButton:disabled {{
                background-color: #bdc3c7;
                color: #7f8c8d;
            }}
        """)
        return button

    def load_random_gif(self):
        """Step 1: Fetch the URL of a random GIF from GIPHY."""
        self.gif_label.setText("Loading GIF metadata...")
        self.gif_label.setStyleSheet("color: #f39c12; border: 2px dashed #34495e; padding: 20px; min-height: 400px;")
        self.load_button.setEnabled(False)
        self.fullscreen_button.setEnabled(False)
        
        request = QNetworkRequest(QUrl(self.GIPHY_RANDOM_URL))
        self.manager.get(request)

    def _handle_network_reply(self, reply: QNetworkReply):
        """Handles responses for both metadata and the raw GIF data."""
        url = reply.url().toString()
        
        if reply.error() != QNetworkReply.NetworkError.NoError:
            error_message = f"Network Error: {reply.errorString()}"
            self.gif_label.setText(f"Error loading GIF: {error_message}")
            self.gif_label.setStyleSheet("color: #e74c3c; border: 2px dashed #c0392b; padding: 20px; min-height: 400px;")
            self.load_button.setEnabled(True)
            return
            
        data = reply.readAll()
        
        if url.startswith("https://api.giphy.com"):
            # Step 1 response: Metadata
            try:
                json_data = json.loads(bytes(data))
                gif_url = json_data.get('data', {}).get('images', {}).get('original', {}).get('url')
                
                if not gif_url:
                    raise ValueError("Could not extract GIF URL from response.")
                    
                self.current_gif_url = gif_url
                self._download_gif_image(gif_url)
                
            except Exception as e:
                self.gif_label.setText(f"Error parsing GIF metadata: {e}")
                self.load_button.setEnabled(True)
                
        elif url == self.current_gif_url:
            # Step 2 response: Raw GIF data
            self.current_gif_data = data
            self._display_gif()

        reply.deleteLater()


    def _download_gif_image(self, url):
        """Step 2: Download the raw GIF image using the URL."""
        self.gif_label.setText("Downloading GIF image...")
        request = QNetworkRequest(QUrl(url))
        self.manager.get(request)
        
    def _display_gif(self):
        """Step 3: Load the raw data into QMovie and display it."""
        try:
            # Stop any previously running movie
            if hasattr(self, 'movie') and self.movie:
                self.movie.stop()
            
            # Close previous buffer if it exists
            if self.gif_buffer and self.gif_buffer.isOpen():
                self.gif_buffer.close()

            # --- Use QBuffer and setDevice ---
            self.gif_buffer = QBuffer(self.current_gif_data)
            if not self.gif_buffer.open(QBuffer.OpenModeFlag.ReadOnly):
                raise Exception("Failed to open GIF data buffer.")

            self.movie = QMovie()
            self.movie.setCacheMode(QMovie.CacheMode.CacheAll)
            self.movie.setDevice(self.gif_buffer) # Use setDevice instead of setData
            
            # Try to get the size of the first frame immediately after setting device
            first_frame_pixmap = self.movie.currentPixmap()
            if not first_frame_pixmap.isNull():
                frame_size = first_frame_pixmap.size()
                
                # Calculate aspect ratio to fit within 80% of current widget size
                max_width = int(self.width() * 0.8) if self.width() > 0 else 600
                max_height = int(self.height() * 0.8) if self.height() > 0 else 400
                
                scaled_size = frame_size.scaled(max_width, max_height, Qt.AspectRatioMode.KeepAspectRatio)
                self.gif_label.setFixedSize(scaled_size)
            else:
                # FIX: Remove setting size to (-1, -1) which causes a warning.
                # The stylesheet min-height will handle the initial size if frame is slow.
                pass 

            # The signal connection ensures dynamic resizing if the initial frame check fails
            self.movie.frameChanged.connect(self._adjust_label_size)
            
            self.gif_label.setMovie(self.movie)
            self.gif_label.setStyleSheet("border: none;")
            self.movie.start()
            
            self.load_button.setEnabled(True)
            self.fullscreen_button.setEnabled(True)
            
        except Exception as e:
            self.gif_label.setText(f"Error displaying GIF: {e}")
            self.load_button.setEnabled(True)
            self.fullscreen_button.setEnabled(False)

    def _adjust_label_size(self):
        """Adjusts the label size to fit the first frame of the GIF and then disconnects."""
        if self.movie.currentFrameNumber() == 0:
            frame_size = self.movie.currentPixmap().size()
            
            # Calculate aspect ratio to fit within 80% of current widget size
            max_width = int(self.width() * 0.8) if self.width() > 0 else 600
            max_height = int(self.height() * 0.8) if self.height() > 0 else 400
            
            scaled_size = frame_size.scaled(max_width, max_height, Qt.AspectRatioMode.KeepAspectRatio)
            self.gif_label.setFixedSize(scaled_size)
            
            # Disconnect the signal after first frame is processed
            try:
                self.movie.frameChanged.disconnect(self._adjust_label_size)
            except TypeError:
                pass # Already disconnected
                
    def show_fullscreen(self):
        """Opens the GIF in a full-screen, frameless dialog."""
        if self.current_gif_data.isEmpty():
            QMessageBox.warning(self, "Warning", "Please wait for the GIF to load before enabling full screen.")
            return

        dialog = FullScreenGifDialog(self.current_gif_data, parent=self.window())
        
        # Get the screen where the main window is displayed
        main_window = self.window()
        screen = QApplication.screenAt(main_window.geometry().center())
        
        if not screen:
            screen = QApplication.primaryScreen()
        
        if screen:
            screen_geometry = screen.geometry()
            dialog.setGeometry(screen_geometry)
        
        dialog.showFullScreen()
        

class SystemInfoPage(BasePage):
    """Displays static system information with universal GPU detection."""
    def __init__(self):
        super().__init__("System Information")
        
        # General System Status
        try:
            total_ram = round(psutil.virtual_memory().total / (1024**3), 1)
            boot_timestamp = psutil.boot_time()
            uptime_seconds = time.time() - boot_timestamp
            
            days = int(uptime_seconds // (24 * 3600))
            hours = int((uptime_seconds % (24 * 3600)) // 3600)
            uptime_str = f"{days} days, {hours} hours"
            boot_time_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(boot_timestamp))

            general_info = {
                "OS Platform": f"{platform.system()} {platform.release()}",
                "Architecture": platform.architecture()[0],
                "Total RAM": f"{total_ram} GB",
                "System Uptime": uptime_str,
                "Boot Time": boot_time_str
            }
        except Exception:
             general_info = {"OS Platform": "N/A", "Architecture": "N/A", "Total RAM": "N/A", "System Uptime": "N/A", "Boot Time": "N/A"}
        
        self._add_info_block("General System Status (Real)", general_info, color="#2ecc71")
        
        # CPU Details
        try:
            processor_model = cpuinfo.get_cpu_info().get('brand_raw', 'Unknown/Generic') if cpuinfo else platform.processor()

            current_freq = psutil.cpu_freq().current
            current_freq_str = f"{current_freq / 1000:.2f} GHz" if current_freq else "N/A"

            cpu_info = {
                "Processor Model": processor_model,
                "Physical Cores": str(psutil.cpu_count(logical=False)),
                "Logical Threads": str(psutil.cpu_count(logical=True)),
                "Base Freq.": f"{psutil.cpu_freq().max / 1000:.2f} GHz",
                "Current Freq.": current_freq_str,
            }
        except Exception as e:
            print(f"Error fetching detailed CPU info: {e}")
            cpu_info = {"Processor Model": "N/A", "Physical Cores": "N/A", "Logical Threads": "N/A", "Base Freq.": "N/A", "Current Freq.": "N/A"}
        
        self._add_info_block("CPU (Central Processing Unit) Details (Real)", cpu_info, color="#f1c40f")

        # GPU Details (Universal Detection)
        gpu_info = {
            "GPU Type": gpu_detector.gpu_type,
            "GPU Model": gpu_detector.gpu_name,
            "VRAM (Total)": f"{gpu_detector.gpu_memory} GB" if gpu_detector.gpu_memory > 0 else "N/A",
            "Driver Version": gpu_detector.driver_version,
            "Live Monitoring": "Available" if gpu_detector.can_monitor else "Limited/Unavailable",
        }
        
        self._add_info_block("GPU (Graphics Processing Unit) Details (Universal Detection)", gpu_info, color="#e74c3c")
        
        # BIOS & Firmware
        bios_info = {}
        if wmi and platform.system() == 'Windows':
            try:
                c = wmi.WMI()
                bios = c.Win32_BIOS()[0]
                
                bios_info = {
                    "BIOS Vendor": bios.Manufacturer,
                    "BIOS Version": bios.SMBIOSBIOSVersion,
                    "Release Date": bios.ReleaseDate.split('.')[0],
                    "System Manufacturer": c.Win32_ComputerSystem()[0].Manufacturer,
                }
            except Exception as e:
                print(f"Error fetching BIOS info with WMI: {e}")
                bios_info = {"BIOS Vendor": "N/A", "BIOS Version": "N/A", "Release Date": "N/A", "System Manufacturer": "N/A"}
        else:
            bios_info = {"BIOS Vendor": "N/A (WMI/Platform not available)", "BIOS Version": "N/A", "Release Date": "N/A", "System Manufacturer": "N/A"}

        self._add_info_block("BIOS & Firmware", bios_info, color="#3498db")
        
        self.layout.addStretch()

    def _add_info_block(self, title, data_dict, color="#bdc3c7"):
        """Creates a styled QGroupBox for system information."""
        group = QGroupBox(title)
        group.setStyleSheet(f"QGroupBox {{ color: {color}; border: 1px solid {color}; margin-top: 10px; padding-top: 20px; }}")
        
        grid = QGridLayout(group)
        grid.setSpacing(15)
        grid.setContentsMargins(20, 30, 20, 20)
        
        row = 0
        for key, value in data_dict.items():
            key_label = QLabel(f"<b style='color: #bdc3c7;'>{key}:</b>")
            key_label.setFont(QFont("Inter", 12))
            
            value_label = self._create_info_label(value)
            
            grid.addWidget(key_label, row, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(value_label, row, 1, Qt.AlignmentFlag.AlignLeft)
            row += 1
            
        self.layout.addWidget(group)
        self.layout.addSpacing(20)


class MonitoringPage(BasePage):
    """Performance monitoring page."""
    def __init__(self):
        super().__init__("Performance Monitoring (Live)")
        
        self.last_io_counters = psutil.disk_io_counters()
        self.last_update_time = time.time()
        
        main_gauges_layout = QHBoxLayout()
        main_gauges_layout.setSpacing(40)

        self.gauges = {
            "CPU": {"widget": CircularProgressBar("CPU Usage", "#3498db", "#2ecc71"), 
                    "psutil_func": lambda: psutil.cpu_percent(interval=0.1)}, 
            
            "Memory": {"widget": CircularProgressBar("Memory", "#f1c40f", "#e67e22"), 
                       "psutil_func": lambda: psutil.virtual_memory().percent},
            
            "Net": {"widget": CircularProgressBar("Net Send (Mbps - Sim)", "#9b59b6", "#8e44ad"),
                         "psutil_func": lambda: random.uniform(25, 75)},
        }
        
        for item in self.gauges.values():
            main_gauges_layout.addWidget(item["widget"], alignment=Qt.AlignmentFlag.AlignCenter)

        self.layout.addLayout(main_gauges_layout)
        self.layout.addWidget(self._create_separator())
        
        stats_group = QGroupBox("System Activity Detail (Real)")
        stats_group.setStyleSheet("QGroupBox { color: #2ecc71; border: 1px solid #2ecc71; margin-top: 10px; padding-top: 20px; }")
        stats_layout = QGridLayout(stats_group)
        stats_layout.setSpacing(15)
        stats_layout.setContentsMargins(20, 30, 20, 20)

        stats_layout.addWidget(QLabel("<b style='color: #bdc3c7;'>CPU Clock Speed:</b>"), 0, 0)
        self.cpu_freq_label = self._create_info_label("N/A")
        stats_layout.addWidget(self.cpu_freq_label, 0, 1)

        stats_layout.addWidget(QLabel("<b style='color: #bdc3c7;'>Disk Read Rate (MB/s):</b>"), 1, 0)
        self.disk_read_label = self._create_info_label("0.00 MB/s")
        stats_layout.addWidget(self.disk_read_label, 1, 1)

        stats_layout.addWidget(QLabel("<b style='color: #bdc3c7;'>Disk Write Rate (MB/s):</b>"), 2, 0)
        self.disk_write_label = self._create_info_label("0.00 MB/s")
        stats_layout.addWidget(self.disk_write_label, 2, 1)
        
        self.layout.addWidget(stats_group)
        self.layout.addWidget(self._create_separator())

        disk_group = QGroupBox("All Disk Usage (Real)")
        disk_group.setStyleSheet("QGroupBox { color: #f1c40f; border: 1px solid #f1c40f; margin-top: 10px; padding-top: 20px; }")
        self.disk_layout = QVBoxLayout(disk_group)
        self.disk_layout.setSpacing(10)
        self.layout.addWidget(disk_group)
        self._setup_disk_usage_widgets()

        self.layout.addStretch()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_monitoring_data)
        self.timer.start(1500)

    def _setup_disk_usage_widgets(self):
        """Creates labels for all detected partitions."""
        self.disk_widgets = {}
        try:
            partitions = psutil.disk_partitions(all=False)
            
            while self.disk_layout.count():
                child = self.disk_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

            for p in partitions:
                hbox = QHBoxLayout()
                
                label = self._create_info_label(f"{p.device} ({p.mountpoint}): ")
                hbox.addWidget(label, 1)
                
                usage_label = self._create_info_label("N/A")
                hbox.addWidget(usage_label, 0, Qt.AlignmentFlag.AlignRight)
                
                self.disk_layout.addLayout(hbox)
                self.disk_widgets[p.mountpoint] = usage_label

        except Exception as e:
            error_label = self._create_info_label(f"Error listing disks: {e}")
            self.disk_layout.addWidget(error_label)

    def _update_monitoring_data(self):
        """Fetches real data and updates all metrics."""
        
        for key, item in self.gauges.items():
            try:
                value = item["psutil_func"]()
                item["widget"].setValue(value)
            except Exception:
                item["widget"].setValue(0)

        try:
            freq = psutil.cpu_freq()
            self.cpu_freq_label.setText(f"{freq.current / 1000:.2f} / {freq.max / 1000:.2f} GHz")
        except Exception:
            self.cpu_freq_label.setText("N/A")

        current_io_counters = psutil.disk_io_counters()
        current_time = time.time()
        time_delta = current_time - self.last_update_time
        
        if self.last_io_counters and time_delta > 0:
            read_rate_bytes = (current_io_counters.read_bytes - self.last_io_counters.read_bytes) / time_delta
            write_rate_bytes = (current_io_counters.write_bytes - self.last_io_counters.write_bytes) / time_delta
            
            read_rate_mb = read_rate_bytes / (1024 * 1024)
            write_rate_mb = write_rate_bytes / (1024 * 1024)
            
            self.disk_read_label.setText(f"{read_rate_mb:.2f} MB/s")
            self.disk_write_label.setText(f"{write_rate_mb:.2f} MB/s")

        self.last_io_counters = current_io_counters
        self.last_update_time = current_time

        for mountpoint, label in self.disk_widgets.items():
            try:
                usage = psutil.disk_usage(mountpoint).percent
                label.setText(f"<b style='color: #2ecc71;'>{usage:.1f}%</b> Used")
            except Exception:
                label.setText("Unavailable")


class GpuPage(BasePage):
    """Displays GPU data with universal GPU support (NVIDIA, AMD, Intel, etc.)."""
    def __init__(self):
        super().__init__(f"GPU Parameters ({gpu_detector.gpu_type})")
        
        self.has_monitoring = gpu_detector.can_monitor
        
        grid = QGridLayout()
        grid.setSpacing(40)

        self.gpu_usage_gauge = CircularProgressBar("GPU Load", "#f39c12", "#d35400")
        self.gpu_temp_gauge = CircularProgressBar("GPU Temp (°C)", "#1abc9c", "#16a085")
        
        grid.addWidget(self.gpu_usage_gauge, 0, 0, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.gpu_temp_gauge, 0, 1, Qt.AlignmentFlag.AlignCenter)
        
        self.layout.addLayout(grid)
        self.layout.addSpacing(30)
        
        detail_group = QGroupBox(f"GPU Live Statistics ({gpu_detector.gpu_type})")
        detail_group.setStyleSheet("QGroupBox { color: #e74c3c; border: 1px solid #e74c3c; margin-top: 10px; padding-top: 20px; }")
        info_grid = QGridLayout(detail_group)
        info_grid.setSpacing(15)
        info_grid.setContentsMargins(20, 30, 20, 20)
        
        info_grid.addWidget(QLabel("<b style='color: #bdc3c7;'>GPU Model:</b>"), 0, 0)
        self.model_label = self._create_info_label(gpu_detector.gpu_name)
        info_grid.addWidget(self.model_label, 0, 1)
        
        info_grid.addWidget(QLabel("<b style='color: #bdc3c7;'>VRAM Used/Total (MB):</b>"), 1, 0)
        self.vram_label = self._create_info_label("N/A")
        info_grid.addWidget(self.vram_label, 1, 1)

        info_grid.addWidget(QLabel("<b style='color: #bdc3c7;'>Graphics Clock (MHz):</b>"), 2, 0)
        self.core_clock_label = self._create_info_label("N/A")
        info_grid.addWidget(self.core_clock_label, 2, 1)
        
        info_grid.addWidget(QLabel("<b style='color: #bdc3c7;'>Memory Clock (MHz):</b>"), 3, 0)
        self.mem_clock_label = self._create_info_label("N/A")
        info_grid.addWidget(self.mem_clock_label, 3, 1)
        
        info_grid.addWidget(QLabel("<b style='color: #bdc3c7;'>Power Draw (W):</b>"), 4, 0)
        self.power_draw_label = self._create_info_label("N/A")
        info_grid.addWidget(self.power_draw_label, 4, 1)
        
        self.layout.addWidget(detail_group)
        
        if not self.has_monitoring:
            warning_label = QLabel("⚠️ Live monitoring unavailable for this GPU. Showing static information only.")
            warning_label.setStyleSheet("color: #f39c12; font-weight: bold; padding: 10px;")
            warning_label.setWordWrap(True)
            self.layout.addWidget(warning_label)
        
        self.layout.addStretch()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_gpu_data)
        self.timer.start(2000) 

    def _update_gpu_data(self):
        """Fetches GPU live monitoring data."""
        if not self.has_monitoring:
            return

        try:
            stats = gpu_detector.get_live_stats()
            
            gpu_load = stats['load']
            self.gpu_usage_gauge.setValue(int(gpu_load))

            temp_val = stats['temp']
            temp_percent = int(min(temp_val, 90) / 90 * 100) 
            self.gpu_temp_gauge.setValue(temp_percent)
            self.gpu_temp_gauge.title = f"GPU Temp ({temp_val}°C)"
            self.gpu_temp_gauge.update()
            
            vram_used = stats['vram_used']
            vram_total = stats['vram_total']
            if vram_total > 0:
                self.vram_label.setText(f"<b style='color: #2ecc71;'>{vram_used} MB</b> / {vram_total} MB")
            else:
                self.vram_label.setText("N/A")
            
            if stats['core_clock'] > 0:
                self.core_clock_label.setText(f"{stats['core_clock']} MHz")
            else:
                self.core_clock_label.setText("N/A")
                
            if stats['mem_clock'] > 0:
                self.mem_clock_label.setText(f"{stats['mem_clock']} MHz")
            else:
                self.mem_clock_label.setText("N/A")
            
            if stats['power'] > 0:
                self.power_draw_label.setText(f"<b style='color: #e74c3c;'>{stats['power']:.2f} W</b>")
            else:
                self.power_draw_label.setText("N/A")
            
        except Exception as e:
            print(f"Error fetching GPU stats: {e}")


class AppsServicesPage(BasePage):
    """Apps and services control page with real process management."""
    def __init__(self):
        super().__init__("Apps & Services Control")
        
        # Filter options
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(10)
        
        filter_label = QLabel("Show:")
        filter_label.setStyleSheet("color: #ecf0f1; font-weight: bold;")
        filter_layout.addWidget(filter_label)
        
        self.filter_all_btn = QPushButton("All Processes")
        self.filter_user_btn = QPushButton("User Processes")
        self.filter_high_cpu_btn = QPushButton("High CPU")
        self.filter_high_mem_btn = QPushButton("High Memory")
        
        for btn in [self.filter_all_btn, self.filter_user_btn, self.filter_high_cpu_btn, self.filter_high_mem_btn]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #34495e;
                    color: #ecf0f1;
                    border: 2px solid #2ecc71;
                    border-radius: 5px;
                    padding: 8px 15px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #2ecc71;
                    color: #2c3e50;
                }
                QPushButton:pressed {
                    background-color: #27ae60;
                }
            """)
            filter_layout.addWidget(btn)
        
        filter_layout.addStretch()
        
        # Refresh button
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 8px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        filter_layout.addWidget(self.refresh_btn)
        
        self.layout.addLayout(filter_layout)
        self.layout.addSpacing(10)
        
        # Process table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["PID", "Name", "CPU %", "Memory %", "Status", "Kill", "Priority"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStyleSheet(
            "QHeaderView::section { background-color: #34495e; color: #ecf0f1; padding: 8px; border: none; font-weight: bold; }"
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet("""
            QTableWidget { 
                background-color: #34495e; 
                color: #ecf0f1; 
                border: none; 
                gridline-color: #2c3e50;
            }
            QTableWidget::item:selected {
                background-color: #2ecc71;
                color: #2c3e50;
            }
        """)
        
        # Column resize modes
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(5, 80)
        self.table.setColumnWidth(6, 100)
        
        self.layout.addWidget(self.table)
        
        # Status bar
        self.status_label = QLabel("Loading processes...")
        self.status_label.setStyleSheet("color: #ecf0f1; padding: 5px; font-style: italic;")
        self.layout.addWidget(self.status_label)
        
        # Connect filter buttons
        self.filter_all_btn.clicked.connect(lambda: self._load_processes("all"))
        self.filter_user_btn.clicked.connect(lambda: self._load_processes("user"))
        self.filter_high_cpu_btn.clicked.connect(lambda: self._load_processes("cpu"))
        self.filter_high_mem_btn.clicked.connect(lambda: self._load_processes("memory"))
        self.refresh_btn.clicked.connect(lambda: self._load_processes(self.current_filter))
        
        # Initial load
        self.current_filter = "all"
        self._load_processes("all")
        
        # Auto-refresh timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self._load_processes(self.current_filter, silent=True))
        self.timer.start(5000)  # Refresh every 5 seconds

    def _load_processes(self, filter_type="all", silent=False):
        """Load and display processes based on filter type."""
        self.current_filter = filter_type
        
        if not silent:
            self.status_label.setText("Loading processes...")
        
        try:
            processes = []
            
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status', 'username']):
                try:
                    info = proc.info
                    
                    # Apply filters
                    if filter_type == "user":
                        # Try to filter out system processes
                        if platform.system() == 'Windows':
                            if info['username'] and 'SYSTEM' in info['username'].upper():
                                continue
                        else:
                            if info['username'] in ['root', 'daemon', 'sys']:
                                continue
                    
                    elif filter_type == "cpu":
                        if info['cpu_percent'] < 5.0:  # Show only >5% CPU
                            continue
                    
                    elif filter_type == "memory":
                        if info['memory_percent'] < 1.0:  # Show only >1% Memory
                            continue
                    
                    processes.append({
                        'pid': info['pid'],
                        'name': info['name'],
                        'cpu': info['cpu_percent'] or 0,
                        'memory': info['memory_percent'] or 0,
                        'status': info['status']
                    })
                
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            # Sort by memory usage (descending)
            if filter_type == "cpu":
                processes.sort(key=lambda x: x['cpu'], reverse=True)
            else:
                processes.sort(key=lambda x: x['memory'], reverse=True)
            
            # Limit to top 50 for performance
            processes = processes[:50]
            
            # Update table
            self.table.setRowCount(len(processes))
            
            for row, proc in enumerate(processes):
                # PID
                pid_item = QTableWidgetItem(str(proc['pid']))
                self.table.setItem(row, 0, pid_item)
                
                # Name
                name_item = QTableWidgetItem(proc['name'])
                self.table.setItem(row, 1, name_item)
                
                # CPU %
                cpu_item = QTableWidgetItem(f"{proc['cpu']:.1f}%")
                if proc['cpu'] > 50:
                    cpu_item.setForeground(QColor("#e74c3c"))
                elif proc['cpu'] > 20:
                    cpu_item.setForeground(QColor("#f39c12"))
                else:
                    cpu_item.setForeground(QColor("#2ecc71"))
                self.table.setItem(row, 2, cpu_item)
                
                # Memory %
                mem_item = QTableWidgetItem(f"{proc['memory']:.1f}%")
                if proc['memory'] > 10:
                    mem_item.setForeground(QColor("#e74c3c"))
                elif proc['memory'] > 5:
                    mem_item.setForeground(QColor("#f39c12"))
                else:
                    mem_item.setForeground(QColor("#2ecc71"))
                self.table.setItem(row, 3, mem_item)
                
                # Status
                status_item = QTableWidgetItem(proc['status'])
                if proc['status'] == 'running':
                    status_item.setForeground(QColor("#2ecc71"))
                elif proc['status'] == 'sleeping':
                    status_item.setForeground(QColor("#3498db"))
                else:
                    status_item.setForeground(QColor("#95a5a6"))
                self.table.setItem(row, 4, status_item)
                
                # Kill Button
                kill_btn = QPushButton("Kill")
                kill_btn.setStyleSheet("""
                    QPushButton { 
                        background-color: #e74c3c; 
                        color: white; 
                        padding: 5px; 
                        border-radius: 5px;
                        font-weight: bold;
                    } 
                    QPushButton:hover { 
                        background-color: #c0392b; 
                    }
                """)
                kill_btn.clicked.connect(lambda checked, p=proc['pid']: self._kill_process(p))
                self.table.setCellWidget(row, 5, kill_btn)
                
                # Priority Button
                priority_btn = QPushButton("Set Priority")
                priority_btn.setStyleSheet("""
                    QPushButton { 
                        background-color: #3498db; 
                        color: white; 
                        padding: 5px; 
                        border-radius: 5px;
                        font-weight: bold;
                    } 
                    QPushButton:hover { 
                        background-color: #2980b9; 
                    }
                """)
                priority_btn.clicked.connect(lambda checked, p=proc['pid'], n=proc['name']: self._set_priority(p, n))
                self.table.setCellWidget(row, 6, priority_btn)
            
            self.status_label.setText(f"Showing {len(processes)} processes ({filter_type} filter)")
        
        except Exception as e:
            self.status_label.setText(f"Error loading processes: {e}")
            print(f"Error in _load_processes: {e}")

    def _kill_process(self, pid):
        """Kill a process by PID."""
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            
            reply = QMessageBox.question(
                self,
                "Confirm Kill Process",
                f"Are you sure you want to kill process:\n\n"
                f"PID: {pid}\n"
                f"Name: {proc_name}\n\n"
                f"This action cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                proc.kill()
                QMessageBox.information(self, "Success", f"Process {proc_name} (PID: {pid}) has been killed.")
                self._load_processes(self.current_filter)
        
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Error", "Process no longer exists.")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Error", "Access denied. Try running as administrator/root.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to kill process: {e}")

    def _set_priority(self, pid, name):
        """Set process priority."""
        try:
            proc = psutil.Process(pid)
            
            # Create priority selection dialog
            dialog = QMessageBox(self)
            dialog.setWindowTitle("Set Process Priority")
            dialog.setText(f"Set priority for:\n{name} (PID: {pid})")
            
            # Platform-specific priority options
            if platform.system() == 'Windows':
                priorities = {
                    "Realtime": psutil.REALTIME_PRIORITY_CLASS,
                    "High": psutil.HIGH_PRIORITY_CLASS,
                    "Above Normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
                    "Normal": psutil.NORMAL_PRIORITY_CLASS,
                    "Below Normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
                    "Idle": psutil.IDLE_PRIORITY_CLASS
                }
            else:
                # Unix-like systems use nice values (-20 to 19)
                priorities = {
                    "Highest": -20,
                    "High": -10,
                    "Normal": 0,
                    "Low": 10,
                    "Lowest": 19
                }
            
            # Add custom buttons
            buttons = {}
            for priority_name in priorities.keys():
                btn = dialog.addButton(priority_name, QMessageBox.ButtonRole.ActionRole)
                buttons[btn] = priorities[priority_name]
            
            cancel_btn = dialog.addButton(QMessageBox.StandardButton.Cancel)
            
            dialog.exec()
            clicked = dialog.clickedButton()
            
            if clicked != cancel_btn and clicked in buttons:
                priority_value = buttons[clicked]
                
                if platform.system() == 'Windows':
                    proc.nice(priority_value)
                else:
                    proc.nice(priority_value)
                
                QMessageBox.information(self, "Success", f"Priority changed for {name}")
                self._load_processes(self.current_filter)
        
        except psutil.NoSuchProcess:
            QMessageBox.warning(self, "Error", "Process no longer exists.")
        except psutil.AccessDenied:
            QMessageBox.warning(self, "Error", "Access denied. Try running as administrator/root.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to set priority: {e}")


class ControlPage(BasePage):
    """System control page with real power management."""
    def __init__(self):
        super().__init__("System Control")
        
        self.layout.setSpacing(25)
        
        # Warning label
        warning_label = QLabel("⚠️ WARNING: These controls perform real system actions!")
        warning_label.setStyleSheet("""
            color: #f39c12; 
            font-weight: bold; 
            font-size: 14pt;
            padding: 15px;
            background-color: #34495e;
            border: 2px solid #f39c12;
            border-radius: 8px;
        """)
        warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(warning_label)
        
        self.layout.addSpacing(20)
        
        # Power controls
        power_group = QGroupBox("Power Management")
        power_group.setStyleSheet("QGroupBox { color: #e74c3c; border: 2px solid #e74c3c; margin-top: 10px; padding-top: 20px; font-weight: bold; }")
        power_layout = QHBoxLayout(power_group)
        power_layout.setSpacing(30)
        
        self._add_control_button(power_layout, "💤 Sleep", "#3498db", "sleep", 
                                "Put the system into sleep/suspend mode")
        self._add_control_button(power_layout, "🔄 Reboot", "#f39c12", "reboot", 
                                "Restart the system")
        self._add_control_button(power_layout, "⏻ Shut Down", "#e74c3c", "shutdown", 
                                "Power off the system completely")
        
        self.layout.addWidget(power_group)
        
        self.layout.addSpacing(20)
        
        # Session controls
        session_group = QGroupBox("Session Management")
        session_group.setStyleSheet("QGroupBox { color: #9b59b6; border: 2px solid #9b59b6; margin-top: 10px; padding-top: 20px; font-weight: bold; }")
        session_layout = QHBoxLayout(session_group)
        session_layout.setSpacing(30)
        
        self._add_control_button(session_layout, "🚪 Log Off", "#9b59b6", "logoff", 
                                "End the current user session")
        self._add_control_button(session_layout, "🔒 Lock Screen", "#8e44ad", "lock", 
                                "Lock the screen")
        
        self.layout.addWidget(session_group)
        
        self.layout.addSpacing(20)
        
        # System info section
        info_group = QGroupBox("Quick System Information")
        info_group.setStyleSheet("QGroupBox { color: #2ecc71; border: 2px solid #2ecc71; margin-top: 10px; padding-top: 20px; font-weight: bold; }")
        info_layout = QGridLayout(info_group)
        info_layout.setSpacing(15)
        info_layout.setContentsMargins(20, 30, 20, 20)
        
        self.uptime_label = self._create_info_label("N/A")
        self.user_label = self._create_info_label("N/A")
        self.hostname_label = self._create_info_label("N/A")
        
        info_layout.addWidget(QLabel("<b style='color: #bdc3c7;'>System Uptime:</b>"), 0, 0)
        info_layout.addWidget(self.uptime_label, 0, 1)
        
        info_layout.addWidget(QLabel("<b style='color: #bdc3c7;'>Current User:</b>"), 1, 0)
        info_layout.addWidget(self.user_label, 1, 1)
        
        info_layout.addWidget(QLabel("<b style='color: #bdc3c7;'>Hostname:</b>"), 2, 0)
        info_layout.addWidget(self.hostname_label, 2, 1)
        
        self.layout.addWidget(info_group)
        
        self.layout.addStretch()
        
        # Update system info
        self._update_system_info()
        
        # Timer to update system info
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_system_info)
        self.timer.start(60000)  # Update every minute

    def _add_control_button(self, layout, text, color, action, description):
        """Add a styled control button."""
        btn = QPushButton(text)
        btn.setFont(QFont("Inter", 14, QFont.Weight.DemiBold)) 
        btn.setFixedSize(QSize(160, 80))
        hover_color = QColor(color).darker(120).name()
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                border-radius: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {hover_color}; 
            }}
            QPushButton:pressed {{
                background-color: {QColor(color).darker(150).name()};
            }}
        """)
        btn.clicked.connect(lambda: self._execute_control(action, text, description))
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _update_system_info(self):
        """Update system information display."""
        try:
            # Uptime
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            days = int(uptime_seconds // (24 * 3600))
            hours = int((uptime_seconds % (24 * 3600)) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            self.uptime_label.setText(f"{days}d {hours}h {minutes}m")
            
            # Current user
            import getpass
            self.user_label.setText(getpass.getuser())
            
            # Hostname
            self.hostname_label.setText(platform.node())
        
        except Exception as e:
            print(f"Error updating system info: {e}")

    def _execute_control(self, action, title, description):
        """Execute system control action."""
        
        # Confirmation dialog
        reply = QMessageBox.warning(
            self,
            f"Confirm: {title}",
            f"{description}\n\n"
            f"Are you sure you want to proceed?\n\n"
            f"⚠️ This will execute a real system command!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply != QMessageBox.StandardButton.Yes:
            return
        
        try:
            system = platform.system()
            
            if action == "shutdown":
                if system == "Windows":
                    subprocess.run(["shutdown", "/s", "/t", "0"], check=True)
                elif system == "Linux":
                    subprocess.run(["systemctl", "poweroff"], check=True)
                elif system == "Darwin":
                    subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
            
            elif action == "reboot":
                if system == "Windows":
                    subprocess.run(["shutdown", "/r", "/t", "0"], check=True)
                elif system == "Linux":
                    subprocess.run(["systemctl", "reboot"], check=True)
                elif system == "Darwin":
                    subprocess.run(["sudo", "shutdown", "-r", "now"], check=True)
            
            elif action == "sleep":
                if system == "Windows":
                    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"], check=True)
                elif system == "Linux":
                    subprocess.run(["systemctl", "suspend"], check=True)
                elif system == "Darwin":
                    subprocess.run(["pmset", "sleepnow"], check=True)
            
            elif action == "logoff":
                if system == "Windows":
                    subprocess.run(["shutdown", "/l"], check=True)
                elif system == "Linux":
                    # Try multiple methods
                    try:
                        subprocess.run(["loginctl", "terminate-user", getpass.getuser()], check=True)
                    except:
                        subprocess.run(["pkill", "-KILL", "-u", getpass.getuser()], check=True)
                elif system == "Darwin":
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to log out'], check=True)
            
            elif action == "lock":
                if system == "Windows":
                    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True)
                elif system == "Linux":
                    # Try multiple lock commands
                    lock_commands = [
                        ["loginctl", "lock-session"],
                        ["xdg-screensaver", "lock"],
                        ["gnome-screensaver-command", "-l"],
                        ["dm-tool", "lock"]
                    ]
                    for cmd in lock_commands:
                        try:
                            subprocess.run(cmd, check=True, timeout=2)
                            break
                        except:
                            continue
                elif system == "Darwin":
                    subprocess.run(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"], check=True)
        
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Error", f"Failed to execute {action}: {e}")
        except FileNotFoundError:
            QMessageBox.critical(self, "Error", f"Command not found. This action may not be supported on your system.")
        except PermissionError:
            QMessageBox.critical(self, "Error", f"Permission denied. Try running as administrator/root.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {e}")
        


# --- Main Dashboard Window ---

class SystemDashboard(QMainWindow):
    """The main application window."""
    def __init__(self, target_monitor, config_resolution, giphy_api_key):
        super().__init__()
        
        self.target_monitor = target_monitor
        self.giphy_api_key = giphy_api_key  # Store the API key
        
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint) # hide from taskbar
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background-color: #2c3e50;")
        
        self._set_precise_geometry()
        
        status = "CUSTOM RESOLUTION MATCH" if config_resolution and \
                 f"{target_monitor.width}x{target_monitor.height}" == config_resolution else \
                 "SMALLEST MONITOR TARGETED"
        self.setWindowTitle(f"System Dashboard Target: {status}")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self._setup_sidebar()
        main_layout.addWidget(self.sidebar)

        self.content_stack = QStackedWidget()
        self._setup_content_stack()
        main_layout.addWidget(self.content_stack, 1)

        self.sidebar.currentRowChanged.connect(self.content_stack.setCurrentIndex)
        self.sidebar.setCurrentRow(1)
        
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _set_precise_geometry(self):
        """Uses QScreen for maximum precision when setting the window geometry."""
        app = QApplication.instance()
        qscreen = app.screenAt(QPoint(self.target_monitor.x, self.target_monitor.y))
        
        if qscreen:
            screen_rect = qscreen.geometry()
            self.setGeometry(
                screen_rect.x(), screen_rect.y(),
                screen_rect.width(), screen_rect.height()
            )
            print("Successfully used QScreen geometry for precise window placement.")
        else:
            self.setGeometry(
                self.target_monitor.x, self.target_monitor.y, 
                self.target_monitor.width, self.target_monitor.height
            )
            print("Warning: Could not reliably map target monitor to QScreen. Using screeninfo geometry as fallback.")

    def _setup_sidebar(self):
        self.sidebar.setFixedWidth(200)
        self.sidebar.setStyleSheet("""
            QListWidget {
                background-color: #34495e; 
                border-right: 3px solid #2ecc71;
                color: #ecf0f1;
                outline: 0;
                padding-top: 20px;
                padding-bottom: 20px;
            }
            QListWidget::item {
                padding: 15px 10px;
                font-size: 14pt;
            }
            QListWidget::item:selected {
                background-color: #2ecc71;
                color: #2c3e50;
                border-radius: 5px;
            }
        """)
        
        menu_items = ["System Info", "Monitoring", "GPU", "Apps/Services", "Control", "GIF"]
        for item in menu_items:
            self.sidebar.addItem(item)
            
    def _setup_content_stack(self):
        self.content_stack.addWidget(SystemInfoPage())
        self.content_stack.addWidget(MonitoringPage())
        self.content_stack.addWidget(GpuPage())
        self.content_stack.addWidget(AppsServicesPage())
        self.content_stack.addWidget(ControlPage())
        self.content_stack.addWidget(GifPage())
        self.content_stack.addWidget(GifPage(self.giphy_api_key))  # Pass API key

    def keyPressEvent(self, event):
        """Handle the Escape key press to close the window."""
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        super().keyPressEvent(event)


# --- Main Execution ---

if __name__ == "__main__":
    
    # START OF FIX: Add this block for PyInstaller on Windows
    if sys.platform.startswith('win'):
        multiprocessing.freeze_support()
    # END OF FIX
    
    if 'PyQt6' not in sys.modules:
        print("\nFATAL ERROR: PyQt6 is not installed. Please run: pip install screeninfo PyQt6 psutil GPUtil")
        sys.exit(1)

    # Load settings from settings.ini
    print("--- Loading settings from settings.ini...")
    settings = load_settings()
    
    config_resolution = settings['config_resolution']
    giphy_api_key = settings['giphy_api_key']
    
    target_monitor = find_target_monitor(config_resolution)


    if not target_monitor:
        QMessageBox.critical(None, "Error", "Failed to find any monitor to display the application.")
        
        if NVML_AVAILABLE and gpu_detector.nvml_handle:
            try:
                nvmlShutdown()
            except:
                pass
        sys.exit(1)

    print(f"--- 2. Launching App on Target Monitor...")
    print(f"--- 3. GPU Detection Summary: {gpu_detector.gpu_type} - {gpu_detector.gpu_name}")

    app = QApplication(sys.argv)
    
    # Pass settings to the window
    window = SystemDashboard(target_monitor, config_resolution, giphy_api_key)
   
    #  START OF ICON SET
    try:
        # Replace 'app_icon.png' with the actual path to your icon file
        icon_path = 'icon.ico' 
        window.setWindowIcon(QIcon(icon_path))
        print(f"--- Application icon set using: {icon_path}")
    except Exception as e:
        print(f"--- WARNING: Could not set application icon. Error: {e}")
    #  END OF ICON SET
   
    window.show()
    
    exit_code = app.exec()
    
    if NVML_AVAILABLE and gpu_detector.nvml_handle:
        try:
            nvmlShutdown()
        except:
            pass

    sys.exit(exit_code)