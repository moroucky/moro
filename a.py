# -*- coding: utf-8 -*-
"""
عارض نماذج ثلاثية الأبعاد احترافي - الإصدار 3.3 (إعادة بناء مع إصلاح شامل لخطأ Assimp)

الميزات:
- واجهة مستخدم PySide6، لوحة تحكم قابلة للرسو
- عرض باستخدام PyVista/pyvistaqt
- تحميل نماذج باستخدام Trimesh (تركيز على GLB/GLTF/FBX) مع استخراج الأنسجة وإحداثيات UV
- لوحة تحكم لإعدادات العرض وخصائص النموذج
- تبديل عرض شبكة الأرضية
- دمج أيقونات SVG (يتطلب توفير ملفات الأيقونات)
- خلفيات HDR (عبر imageio)، إعدادات إضاءة مسبقة
- واجهة مستخدم هيكل عظمي/رسوم متحركة (تشغيل الرسوم المتحركة يتطلب تطبيقاً إضافياً)
- معالجة قوية للأخطاء وفحص التبعيات
- نافذة معاينة الأنسجة
- حفظ واستعادة إعدادات النافذة (الحجم، الموضع، حالة لوحة الرسو، آخر دليل)
- إصلاح أخطاء الإضاءة وتجاوز اللون/النسيج ومعاينة النسيج.
- تحسين التعامل مع تحميل ملفات FBX وتوفير إرشادات حول تبعية pyassimp والمكتبة الأصلية Assimp.
"""

import sys
import os
import traceback
import numpy as np
import pyvista as pv
import logging # لتسجيل رسائل Trimesh والرسائل العامة

# --- استيراد مكتبات Qt ---
from PySide6 import QtCore, QtGui, QtWidgets, QtSvg, QtSvgWidgets
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QFileDialog, QMessageBox, QStatusBar, QColorDialog, QLabel, QPushButton,
    QCheckBox, QSlider, QDockWidget, QSpacerItem, QSizePolicy, QGroupBox,
    QComboBox, QDoubleSpinBox, QListWidget, QDialog, QDialogButtonBox, QScrollArea,
    QAbstractButton # Added QAbstractButton here
)
from PySide6.QtGui import QAction, QIcon, QKeySequence, QColor, QPalette, QPixmap, QImage
from PySide6.QtCore import Qt, Slot, QSize, Signal, QSettings, QTimer # Added QTimer for potential animation

# --- فحص التبعيات والإعدادات العامة ---
# فحص المكتبات الأساسية والاختيارية
print("[SETUP] Checking dependencies...")
# pyvistaqt is essential, exit if not found
try:
    from pyvistaqt import QtInteractor
    PYVISTAQT_AVAILABLE = True
    print("  [OK] pyvistaqt found.")
except ImportError:
    print("FATAL ERROR: pyvistaqt is required but not found.")
    print("Please install it: pip install pyvistaqt PySide6")
    sys.exit(1)

# Trimesh is highly recommended for advanced loading
try:
    import trimesh
    # Configure Trimesh logging level (e.g., logging.WARNING to hide verbose warnings)
    trimesh.util.attach_to_log(logging.WARNING)
    TRIMESH_AVAILABLE = True
    print("  [OK] Trimesh found (for advanced loading).")
except ImportError:
    TRIMESH_AVAILABLE = False
    print("[WARN] Trimesh not found. Loading capabilities will be limited (GLTF/GLB textures, animations might not load).")
    print("       Install it for better support: pip install trimesh[easy]")


# Check specifically for pyassimp for FBX support in Trimesh
PYASSIMP_AVAILABLE = False
# Attempt to import pyassimp and handle potential errors, including the native library not found error
if TRIMESH_AVAILABLE:
    try:
        import pyassimp
        # If the import succeeds, check if the errors module and AssimpError exist
        # This check is defensive in case the pyassimp package is partially installed or structured unexpectedly
        if hasattr(pyassimp, 'errors') and hasattr(pyassimp.errors, 'AssimpError'):
             AssimpError = pyassimp.errors.AssimpError
             PYASSIMP_AVAILABLE = True
             print("  [OK] pyassimp found (for Trimesh FBX support).")
        else:
             # pyassimp package imported, but expected errors module/class not found
             print("[WARN] pyassimp package imported, but 'pyassimp.errors.AssimpError' not found.")
             print("       FBX loading via Trimesh might be limited.")
             PYASSIMP_AVAILABLE = False # Treat as not fully available for FBX


    except ImportError:
        # This catches if the main pyassimp package is not installed at all
        print("[WARN] pyassimp Python package not found.")
        print("       Install it for FBX support via Trimesh: pip install pyassimp")
        PYASSIMP_AVAILABLE = False # Ensure it's False
        AssimpError = None # Ensure AssimpError is not defined in this case

    except Exception as e:
        # This catches any other exception during the pyassimp import process,
        # including the AssimpError if the native library is missing.
        # We need to check if the caught exception is the specific AssimpError.
        # We can only do this check if we managed to import pyassimp.errors.AssimpError successfully earlier,
        # OR if the exception itself is an instance of pyassimp.errors.AssimpError (if it was raised directly).

        # Try to get AssimpError class defensively if it wasn't imported earlier
        _AssimpError_class = None
        try:
            import pyassimp.errors
            _AssimpError_class = pyassimp.errors.AssimpError
        except ImportError:
            pass # Cannot get the class, proceed without specific check

        if _AssimpError_class is not None and isinstance(e, _AssimpError_class):
             # Caught the specific native library error
             print(f"[WARN] pyassimp found, but native Assimp library not found: {e}")
             print("       FBX loading via Trimesh will be disabled.")
             print("       Please ensure the Assimp shared library (DLL on Windows) is installed and accessible in your system's PATH.")
        else:
             # Caught some other unexpected error during import
             print(f"[ERROR] Unexpected error during pyassimp import: {type(e).__name__}: {e}")
             traceback.print_exc(limit=1) # Print limited traceback

        PYASSIMP_AVAILABLE = False # Ensure it's False
        AssimpError = None # Ensure AssimpError is not defined after this failure


# Pillow is required for texture preview
try:
    from PIL import Image, ImageQt
    PILLOW_AVAILABLE = True
    # Prevent DecompressionBombError for large textures
    Image.MAX_IMAGE_PIXELS = None
    print("  [OK] Pillow found (for texture handling).")
except ImportError:
    PILLOW_AVAILABLE = False
    print("[WARN] Pillow (PIL) not found. Texture loading/preview will be disabled.")
    print("       Install it for texture support: pip install Pillow")

# imageio is required for HDR loading
try:
    import imageio.v3 as iio
    IMAGEIO_AVAILABLE = True
    print("  [OK] imageio found (for HDR loading).")
except ImportError:
    IMAGEIO_AVAILABLE = False
    print("[WARN] imageio not found. HDR environment loading will be disabled.")
    print("       Install it for HDR support: pip install imageio")

# Configure PyVista theme
pv.set_plot_theme("document") # Or "dark", "paraview", etc.

# --- Constants ---
APP_NAME = "Pro Viewer 3D"
APP_VERSION = "3.3"
ORG_NAME = "YourOrg" # Used for QSettings

# Texture type keys (match Trimesh PBR material attributes where possible)
TEX_BASE_COLOR = 'baseColorTexture'
TEX_METALLIC_ROUGHNESS = 'metallicRoughnessTexture'
TEX_NORMAL = 'normalTexture'
TEX_OCCLUSION = 'occlusionTexture'
TEX_EMISSIVE = 'emissiveTexture'
# Fallback key if only a single texture is found directly on the material
TEX_GENERIC_IMAGE = 'image'
ALL_TEX_TYPES = [TEX_BASE_COLOR, TEX_METALLIC_ROUGHNESS, TEX_NORMAL, TEX_OCCLUSION, TEX_EMISSIVE]

# --- Helper function for loading icons ---
ICON_CACHE = {}
DEFAULT_ICON_SIZE = QSize(20, 20)
# Paths to search for icon files
# Ensure an 'icons' folder exists in the same directory as your Python file and contains the required SVG files.
ICON_SEARCH_PATHS = ['.', 'icons', os.path.join(os.path.dirname(__file__), 'icons')]

# List of icon files the application expects (must be provided in one of the search paths)
REQUIRED_ICON_FILES = [
    "cube.svg",         # Main application icon
    "view-3d.svg",      # Reset camera
    "color-picker.svg", # Background color picker
    "image.svg",        # Load HDR
    "x-circle.svg",     # Clear HDR
    "eye.svg",          # Texture preview
    "play.svg",         # Play animation
    "stop-circle.svg",  # Stop animation
    "file-plus.svg",    # Open file
    "file-minus.svg",   # Close file
    "log-out.svg",      # Exit
    "sidebar.svg",      # Toggle control panel
    "grid.svg",         # Toggle grid
    "info.svg",         # About app
    "help-circle.svg"   # About Qt
]


def find_icon_file(filename):
    """Searches for the icon file in the predefined paths."""
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename
    for path in ICON_SEARCH_PATHS:
        full_path = os.path.join(path, filename)
        if os.path.exists(full_path):
            return full_path
    return None # Not found

def load_icon(filename, size=DEFAULT_ICON_SIZE):
    """
    Loads an SVG icon from a file, caches it, and resizes it.
    Returns a QIcon. If the file is not found or invalid, returns an empty QIcon
    or a placeholder icon depending on configuration.
    """
    cache_key = (filename, size.width(), size.height())
    if cache_key in ICON_CACHE:
        return ICON_CACHE[cache_key]

    filepath = find_icon_file(filename)
    if not filepath:
        # Return a placeholder or empty icon if file not found
        # print(f"[WARN] Icon file not found: {filename}") # Warning is already printed at startup
        # Option 1: Empty icon
        icon = QIcon()
        # Option 2: Gray placeholder (useful for debugging missing icons)
        # placeholder = QPixmap(size)
        # placeholder.fill(Qt.gray)
        # icon = QIcon(placeholder)
        ICON_CACHE[cache_key] = icon # Cache the result (empty or placeholder)
        return icon

    try:
        # Use QSvgRenderer for better scaling and SVG validation
        renderer = QtSvg.QSvgRenderer(filepath)
        if not renderer.isValid():
             print(f"[WARN] Invalid SVG file: {filepath}")
             icon = QIcon() # Return empty icon for invalid SVG
             ICON_CACHE[cache_key] = icon
             return icon

        # Create a QPixmap and render the SVG onto it at the desired size
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent) # Start with a transparent background
        painter = QtGui.QPainter(pixmap)
        renderer.render(painter)
        painter.end()

        icon = QIcon(pixmap)
        ICON_CACHE[cache_key] = icon
        # print(f"  [Icon Load] Loaded and cached: {filename} from {filepath}")
        return icon
    except Exception as e:
        print(f"[ERROR] Failed to load or render icon '{filename}' from '{filepath}': {e}")
        traceback.print_exc() # Print detailed error
        icon = QIcon() # Return empty icon on error
        ICON_CACHE[cache_key] = icon
        return icon

# Check for required icon files on startup
print("[SETUP] Checking for required icon files...")
missing_icons = [icon_name for icon_name in REQUIRED_ICON_FILES if find_icon_file(icon_name) is None]
if missing_icons:
    print(f"[WARN] {len(missing_icons)} required icon file(s) not found in search paths: {', '.join(missing_icons)}")
    print("       Please ensure these SVG files are in an 'icons' folder next to the script, or in one of the paths:", ICON_SEARCH_PATHS)
else:
    print("  [OK] All required icon files found.")


print("[SETUP] Initial checks and constants defined.")

# ==================================================
#           Texture Preview Dialog Class
# ==================================================
class TexturePreviewDialog(QDialog):
    """Simple dialog window to display a preview of a texture image."""
    def __init__(self, texture_name, pil_image, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Texture Preview: {texture_name}")
        self.setMinimumSize(400, 300)

        layout = QVBoxLayout(self)

        # Texture title label
        self.title_label = QLabel()
        layout.addWidget(self.title_label)

        # Scroll area for the image
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setBackgroundRole(QPalette.Dark) # Dark background for the image area
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setBackgroundRole(QPalette.Dark)
        self.scroll_area.setWidget(self.image_label)
        layout.addWidget(self.scroll_area)

        # Dialog buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)

        # Load and display the image
        if pil_image and PILLOW_AVAILABLE:
            try:
                # Convert PIL image to QPixmap
                # Ensure image is in a format Qt can handle, RGBA is generally safe
                if pil_image.mode != 'RGBA':
                     pil_image = pil_image.convert("RGBA")
                q_image = ImageQt.ImageQt(pil_image)
                pixmap = QPixmap.fromImage(q_image)

                # Set the title with image info
                self.title_label.setText(f"<b>{texture_name}</b> ({pil_image.width}x{pil_image.height}, Mode: {pil_image.mode})")

                # Scale QPixmap for display if it's too large (optional, adjust max_dim)
                max_dim = 800
                if pixmap.width() > max_dim or pixmap.height() > max_dim:
                    pixmap = pixmap.scaled(max_dim, max_dim, Qt.KeepAspectRatio, Qt.SmoothTransformation)

                self.image_label.setPixmap(pixmap)
                # Adjust dialog size to fit the image (with some margin)
                self.resize(max(400, pixmap.width() + 40), max(300, pixmap.height() + 80))

            except Exception as e:
                self.title_label.setText(f"<b>{texture_name}</b><br><font color='red'>Error displaying preview.</font>")
                self.image_label.setText("Preview Error")
                print(f"[ERROR] Texture Preview Error for '{texture_name}': {e}")
                traceback.print_exc()
        else:
            self.title_label.setText(f"<b>{texture_name}</b><br>No Image Data or Pillow library missing.")
            self.image_label.setText("No Image Available")


# ==================================================
#           Control Panel Widget Class
# ==================================================
class ControlPanel(QWidget):
    """Advanced UI panel using QGridLayout for better organization."""

    # --- Signals (emitted when a control changes) ---
    reset_camera_signal = Signal()
    # toggle_axes_signal = Signal(bool) # Handled by MainWindow action/slot sync
    # toggle_grid_signal = Signal(bool) # Handled by MainWindow action/slot sync
    change_bgcolor_signal = Signal()
    lighting_preset_changed_signal = Signal(str)
    load_hdr_signal = Signal()
    clear_hdr_signal = Signal()

    toggle_edges_signal = Signal(bool)
    representation_changed_signal = Signal(str) # 'surface', 'wireframe', 'points'
    opacity_changed_signal = Signal(int) # 0-100
    point_size_changed_signal = Signal(float)
    color_override_signal = Signal(object) # QColor or None to clear override

    texture_visibility_changed_signal = Signal(str, bool) # tex_type, is_visible
    view_texture_signal = Signal(str) # tex_type to view

    toggle_skeleton_signal = Signal(bool) # Placeholder
    play_animation_signal = Signal(str) # Placeholder (animation name)
    stop_animation_signal = Signal() # Placeholder

    def __init__(self, parent=None):
        super().__init__(parent)
        print("  [UI Panel] Initializing Control Panel...")
        self._override_color_internal = None # Stores the QColor for override
        self._texture_widgets = {} # Stores {'tex_type': {'checkbox': QCheckBox, 'view_btn': QPushButton, 'label': QLabel}}
        self._loaded_textures_cache = {} # Stores {'tex_type': PIL.Image} from the last loaded model
        self._setup_ui()
        print("  [UI Panel] UI setup complete.")

    def _setup_ui(self):
        """Creates and arranges all UI elements in the control panel."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10) # Slightly larger inner margin
        main_layout.setSpacing(12) # Slightly larger spacing between groups

        # --- View Settings Group ---
        view_group = QGroupBox("View Settings")
        view_layout = QGridLayout(view_group) # Use grid for precise alignment
        view_layout.setSpacing(8)
        view_layout.setColumnStretch(1, 1) # Allow middle columns to stretch
        view_layout.setColumnStretch(3, 1)

        # Row 0: Reset Camera, Toggle Axes, Toggle Grid
        self.reset_cam_button = QPushButton(load_icon("view-3d.svg"), " Reset Camera")
        self.reset_cam_button.setToolTip("Reset camera view to fit the model")
        self.reset_cam_button.clicked.connect(self.reset_camera_signal.emit)
        view_layout.addWidget(self.reset_cam_button, 0, 0, 1, 2) # Span two columns

        # Axes checkbox (connected in MainWindow for sync with action)
        self.axes_checkbox = QCheckBox("Show Axes")
        self.axes_checkbox.setChecked(True) # Axes are visible by default
        self.axes_checkbox.setToolTip("Toggle visibility of the coordinate axes")
        # self.axes_checkbox.toggled.connect(self.toggle_axes_signal.emit) # Connected in MainWindow
        view_layout.addWidget(self.axes_checkbox, 0, 2)

        # Grid checkbox (connected in MainWindow for sync with action)
        self.grid_checkbox = QCheckBox("Show Grid") # Grid checkbox
        self.grid_checkbox.setChecked(False) # Grid is hidden by default
        self.grid_checkbox.setToolTip("Toggle visibility of the ground grid plane")
        # self.grid_checkbox.toggled.connect(self.toggle_grid_signal.emit) # Connected in MainWindow
        view_layout.addWidget(self.grid_checkbox, 0, 3)

        # Row 1: Background Color, Lighting Preset
        self.bgcolor_button = QPushButton(load_icon("color-picker.svg"), " Background Color")
        self.bgcolor_button.setToolTip("Change the background color of the viewer")
        self.bgcolor_button.clicked.connect(self.change_bgcolor_signal.emit)
        view_layout.addWidget(self.bgcolor_button, 1, 0, 1, 2) # Span two columns

        self.lighting_combo = QComboBox()
        self.lighting_combo.addItems(["Default Kit", "None", "Cad", "Bright", "Environment (HDR)"])
        self.lighting_combo.setToolTip("Select a lighting preset (Environment requires HDR)")
        self.lighting_combo.currentTextChanged.connect(self.lighting_preset_changed_signal.emit)
        view_layout.addWidget(QLabel("Lighting:"), 1, 2, Qt.AlignRight | Qt.AlignVCenter)
        view_layout.addWidget(self.lighting_combo, 1, 3)

        # Row 2: HDR Controls
        self.load_hdr_button = QPushButton(load_icon("image.svg"), " Load HDR")
        self.load_hdr_button.setToolTip("Load an HDR or EXR file for environment lighting")
        self.load_hdr_button.clicked.connect(self.load_hdr_signal.emit)
        self.load_hdr_button.setEnabled(IMAGEIO_AVAILABLE) # Enable only if library exists
        if not IMAGEIO_AVAILABLE: self.load_hdr_button.setToolTip("Requires 'imageio' library")
        view_layout.addWidget(self.load_hdr_button, 2, 0, 1, 2)

        self.clear_hdr_button = QPushButton(load_icon("x-circle.svg"), " Clear HDR")
        self.clear_hdr_button.setToolTip("Remove the current HDR environment")
        self.clear_hdr_button.clicked.connect(self.clear_hdr_signal.emit)
        self.clear_hdr_button.setEnabled(False) # Enable only when HDR is loaded
        view_layout.addWidget(self.clear_hdr_button, 2, 2, 1, 2)

        main_layout.addWidget(view_group)

        # --- Model Display Properties Group ---
        model_group = QGroupBox("Model Display")
        model_layout = QGridLayout(model_group)
        model_layout.setSpacing(8)
        model_layout.setColumnStretch(1, 1) # Allow slider/spinbox column to stretch

        # Row 0: Representation Style (Surface, Wireframe, Points)
        rep_label = QLabel("Style:")
        model_layout.addWidget(rep_label, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)

        rep_widget = QWidget() # Use a widget + hbox for button group
        rep_hbox = QHBoxLayout(rep_widget)
        rep_hbox.setContentsMargins(0,0,0,0)
        rep_hbox.setSpacing(4)
        self.rep_surface_btn = QPushButton("Surface")
        self.rep_wireframe_btn = QPushButton("Wireframe")
        self.rep_points_btn = QPushButton("Points")
        self.rep_surface_btn.setCheckable(True); self.rep_wireframe_btn.setCheckable(True); self.rep_points_btn.setCheckable(True)
        self.rep_surface_btn.setChecked(True) # Default is Surface
        self.rep_surface_btn.setToolTip("Render model as solid surfaces")
        self.rep_wireframe_btn.setToolTip("Render model as lines (edges)")
        self.rep_points_btn.setToolTip("Render model as points (vertices)")

        # Button group ensures only one button is checked at a time
        self.rep_style_group = QtWidgets.QButtonGroup(self)
        self.rep_style_group.setExclusive(True)
        self.rep_style_group.addButton(self.rep_surface_btn, 0) # Assign IDs if needed
        self.rep_style_group.addButton(self.rep_wireframe_btn, 1)
        self.rep_style_group.addButton(self.rep_points_btn, 2)

        # Connect signals
        self.rep_style_group.buttonClicked.connect(self._on_representation_button_clicked)

        rep_hbox.addWidget(self.rep_surface_btn)
        rep_hbox.addWidget(self.rep_wireframe_btn)
        rep_hbox.addWidget(self.rep_points_btn)
        model_layout.addWidget(rep_widget, 0, 1, 1, 2) # Span two columns

        # Row 1: Show Edges, Point Size
        self.edges_checkbox = QCheckBox("Show Edges")
        self.edges_checkbox.setToolTip("Overlay edges on top of the surface representation")
        self.edges_checkbox.toggled.connect(self.toggle_edges_signal.emit)
        model_layout.addWidget(self.edges_checkbox, 1, 0)

        self.point_size_spinbox = QDoubleSpinBox()
        self.point_size_spinbox.setRange(0.5, 25.0)
        self.point_size_spinbox.setValue(5.0)
        self.point_size_spinbox.setSingleStep(0.5)
        self.point_size_spinbox.setDecimals(1)
        self.point_size_spinbox.setToolTip("Set size for 'Points' representation")
        self.point_size_spinbox.valueChanged.connect(self.point_size_changed_signal.emit)
        model_layout.addWidget(QLabel("Point Size:"), 1, 1, Qt.AlignRight | Qt.AlignVCenter)
        model_layout.addWidget(self.point_size_spinbox, 1, 2)

        # Row 2: Opacity
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(100)
        self.opacity_slider.setToolTip("Adjust model transparency (0=invisible, 100=opaque)")
        self.opacity_value_label = QLabel("100%") # Display current value
        self.opacity_value_label.setMinimumWidth(35) # Ensure space for "100%"
        self.opacity_slider.valueChanged.connect(self._on_opacity_slider_change) # Connect internal slot first
        model_layout.addWidget(QLabel("Opacity:"), 2, 0)
        model_layout.addWidget(self.opacity_slider, 2, 1)
        model_layout.addWidget(self.opacity_value_label, 2, 2)

        # Row 3: Color Override
        self.color_override_checkbox = QCheckBox("Override Color")
        self.color_override_checkbox.setToolTip("Force a single color, ignoring textures/vertex colors")
        self.color_override_button = QPushButton("...") # Color picker button
        self.color_override_button.setMaximumWidth(40)
        self.color_override_button.setEnabled(False) # Enabled by checkbox
        self.color_override_checkbox.toggled.connect(self._on_color_override_toggled)
        self.color_override_button.clicked.connect(self._on_select_override_color)
        model_layout.addWidget(self.color_override_checkbox, 3, 0)
        model_layout.addWidget(self.color_override_button, 3, 1, 1, 1, Qt.AlignLeft) # Place button next to checkbox

        main_layout.addWidget(model_group)

        # --- Texture Maps Group ---
        tex_group = QGroupBox("Texture Maps")
        self.texture_layout = QGridLayout(tex_group)
        self.texture_layout.setSpacing(6) # Tighter spacing for texture list
        self.texture_layout.setColumnStretch(0, 1) # Allow name column to expand

        # Header row
        self.texture_layout.addWidget(QLabel("<b>Map Type</b>"), 0, 0)
        self.texture_layout.addWidget(QLabel("<b>Vis</b>"), 0, 1, Qt.AlignCenter) # Visibility toggle
        self.texture_layout.addWidget(QLabel("<b>View</b>"), 0, 2, Qt.AlignCenter) # Preview button

        # Create rows for each texture type
        tex_display_labels = {
            TEX_BASE_COLOR: "Base Color",
            TEX_METALLIC_ROUGHNESS: "Metal/Rough",
            TEX_NORMAL: "Normal",
            TEX_OCCLUSION: "Occlusion",
            TEX_EMISSIVE: "Emissive"
        }
        for i, tex_type in enumerate(ALL_TEX_TYPES):
            row = i + 1
            display_name = tex_display_labels.get(tex_type, tex_type)
            label = QLabel(display_name)

            # Visibility checkbox (Note: currently only BaseColor visually affects rendering directly)
            vis_checkbox = QCheckBox()
            vis_checkbox.setToolTip(f"Toggle visibility effect (currently only for Base Color)")
            # Use lambda to capture the correct tex_type for the slot
            vis_checkbox.toggled.connect(lambda state, t=tex_type: self.texture_visibility_changed_signal.emit(t, state))

            # Preview button
            view_button = QPushButton(load_icon("eye.svg"), "")
            view_button.setMaximumWidth(35) # Small button
            view_button.setToolTip(f"Preview the {display_name} texture image")
            view_button.clicked.connect(lambda t=tex_type: self.view_texture_signal.emit(t))

            self.texture_layout.addWidget(label, row, 0)
            self.texture_layout.addWidget(vis_checkbox, row, 1, Qt.AlignCenter)
            self.texture_layout.addWidget(view_button, row, 2, Qt.AlignCenter)

            # Store UI elements for later access
            self._texture_widgets[tex_type] = {'checkbox': vis_checkbox, 'view_btn': view_button, 'label': label}

        main_layout.addWidget(tex_group)

        # --- Skeleton and Animation Group (Placeholders) ---
        skel_anim_group = QGroupBox("Structure & Animation")
        skel_anim_layout = QVBoxLayout(skel_anim_group)
        skel_anim_layout.setSpacing(8)

        # Skeleton toggle (Placeholder)
        self.skeleton_checkbox = QCheckBox("Show Skeleton")
        self.skeleton_checkbox.setToolTip("Toggle visibility of the model's skeleton (if loaded)")
        self.skeleton_checkbox.setEnabled(False) # Disabled until skeleton data is loaded
        self.skeleton_checkbox.toggled.connect(self.toggle_skeleton_signal.emit)
        skel_anim_layout.addWidget(self.skeleton_checkbox)

        # Animation list (Placeholder)
        anim_label = QLabel("Animations:")
        skel_anim_layout.addWidget(anim_label)
        self.animation_list = QListWidget()
        self.animation_list.setFixedHeight(80) # Set fixed height
        self.animation_list.setEnabled(False) # Disabled until animations are loaded
        self.animation_list.setToolTip("List of animations found in the model")
        # Connect item change to enable play button
        self.animation_list.currentItemChanged.connect(lambda current, previous: self.play_button.setEnabled(current is not None))
        skel_anim_layout.addWidget(self.animation_list)

        # Animation controls (Placeholders)
        anim_controls_layout = QHBoxLayout()
        self.play_button = QPushButton(load_icon("play.svg"), " Play")
        self.play_button.setToolTip("Play selected animation (Not Implemented)")
        self.play_button.setEnabled(False) # Disabled until animation is selected
        self.play_button.clicked.connect(self._on_play_animation) # Connect internal slot

        self.stop_button = QPushButton(load_icon("stop-circle.svg"), " Stop")
        self.stop_button.setToolTip("Stop current animation (Not Implemented)")
        self.stop_button.setEnabled(False) # Disabled until animations are loaded
        self.stop_button.clicked.connect(self.stop_animation_signal.emit) # Connect directly
        anim_controls_layout.addWidget(self.play_button)
        anim_controls_layout.addWidget(self.stop_button)
        anim_controls_layout.addStretch() # Push buttons to the left
        skel_anim_layout.addLayout(anim_controls_layout)

        # Add note about implementation status
        anim_note = QLabel("<small><i>Animation playback requires<br>further implementation.</i></small>")
        anim_note.setAlignment(Qt.AlignCenter)
        skel_anim_layout.addWidget(anim_note)

        main_layout.addWidget(skel_anim_group)

        # --- Spacer ---
        # Pushes all group boxes to the top
        main_layout.addSpacerItem(QSpacerItem(10, 10, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))

        # --- Initial State ---
        # Disable controls that depend on a loaded model
        self.set_model_controls_enabled(False)
        self.set_texture_controls_enabled(False)
        self.set_skel_anim_controls_enabled(has_skeleton=False, has_animations=False)

    # --- Internal Slots and Helper Functions ---
    @Slot(int)
    def _on_opacity_slider_change(self, value):
        """Updates the label and emits the signal when the slider is moved."""
        self.opacity_value_label.setText(f"{value}%")
        self.opacity_changed_signal.emit(value) # Emit the public signal

    @Slot(bool)
    def _on_color_override_toggled(self, checked):
        """Enables/disables the color button and emits the signal."""
        self.color_override_button.setEnabled(checked)
        # If checked, emit the current color, otherwise emit None to clear override
        color_to_emit = self._override_color_internal if checked and self._override_color_internal else None
        self.color_override_signal.emit(color_to_emit)
        # Update the visual appearance of the button immediately when unchecked
        if not checked:
             self._update_color_button_visual(None)

    @Slot()
    def _on_select_override_color(self):
        """Opens the color dialog and updates the internal color."""
        initial_color = self._override_color_internal or Qt.GlobalColor.white
        new_color = QColorDialog.getColor(initial_color, self, "Select Override Color")
        if new_color.isValid():
            self._override_color_internal = new_color
            self._update_color_button_visual(new_color)
            # If the override checkbox is active, emit the new color signal
            if self.color_override_checkbox.isChecked():
                self.color_override_signal.emit(self._override_color_internal)

    def _update_color_button_visual(self, q_color=None):
        """Updates the background color of the color picker button."""
        palette = self.color_override_button.palette()
        if q_color and q_color.isValid():
            # Set button background color
            palette.setColor(QPalette.Button, q_color)
            # Set text color based on background brightness for readability
            brightness = (q_color.red() * 299 + q_color.green() * 587 + q_color.blue() * 114) / 1000
            text_color = Qt.black if brightness > 128 else Qt.white
            palette.setColor(QPalette.ButtonText, text_color)
            self.color_override_button.setText("") # Clear text when color is set
        else:
            # Reset to default button color and text appearance
            palette = QApplication.palette() # Get the default application palette
            self.color_override_button.setText("...") # Restore text
        self.color_override_button.setPalette(palette)
        self.color_override_button.style().polish(self.color_override_button) # Ensure style is applied


    @Slot(QAbstractButton) # Receives the clicked button from QButtonGroup
    def _on_representation_button_clicked(self, button):
        """Responds to clicks on the representation buttons (Surface, Wireframe, Points)."""
        style = button.text().lower() # Get the lower-case text of the button ('surface', 'wireframe', 'points')
        print(f"  [UI Panel] Representation button clicked: {style}")
        self.representation_changed_signal.emit(style) # Emit the public signal

    @Slot()
    def _on_play_animation(self):
        """Internal slot to handle the play button click."""
        selected_item = self.animation_list.currentItem()
        if selected_item:
            anim_name = selected_item.text()
            self.play_animation_signal.emit(anim_name)
        else:
            # Optionally show a message if no animation is selected
            print("[UI Panel] Play clicked, but no animation selected.")

    # --- Public methods to update panel state ---
    def set_model_controls_enabled(self, enabled):
        """Enables/disables all UI elements in the Model Display group."""
        # Find the QGroupBox by title (more robust than assuming order)
        model_group = next((c for c in self.findChildren(QGroupBox) if c.title() == "Model Display"), None)
        if model_group:
            model_group.setEnabled(enabled)
        if not enabled:
            # Reset controls to default when disabled
            self.reset_model_controls()

    def set_texture_controls_enabled(self, enabled, available_textures=None):
        """Enables/disables the texture group and individual texture rows."""
        tex_group = next((c for c in self.findChildren(QGroupBox) if c.title() == "Texture Maps"), None)
        if tex_group:
            tex_group.setEnabled(enabled)

        available_textures = available_textures or []
        # Clear the internal cache when disabled or loading a new model
        if not enabled:
            self._loaded_textures_cache.clear()

        # Enable/disable individual rows based on available textures
        for tex_type, widgets in self._texture_widgets.items():
            # Enable the row if the group is enabled AND the texture data is available for this type
            has_tex_data = enabled and (tex_type in available_textures)
            widgets['label'].setEnabled(has_tex_data)
            widgets['checkbox'].setEnabled(has_tex_data)
            widgets['view_btn'].setEnabled(has_tex_data and PILLOW_AVAILABLE) # Preview button requires Pillow
            if not PILLOW_AVAILABLE:
                widgets['view_btn'].setToolTip("Requires 'Pillow' library for preview")


    def set_skel_anim_controls_enabled(self, has_skeleton, has_animations):
        """Enables/disables skeleton and animation controls."""
        skel_group = next((c for c in self.findChildren(QGroupBox) if c.title() == "Structure & Animation"), None)
        if skel_group:
            # Enable the group if either skeleton or animations are present
            skel_group.setEnabled(has_skeleton or has_animations)

        self.skeleton_checkbox.setEnabled(has_skeleton)
        self.animation_list.setEnabled(has_animations)
        # Enable play button only if animations are available AND an item is selected
        self.play_button.setEnabled(has_animations and self.animation_list.currentItem() is not None)
        self.stop_button.setEnabled(has_animations) # can stop animation even if none selected (e.g. if one was playing)

        # Ensure state consistency
        if not has_skeleton:
            self.skeleton_checkbox.setChecked(False)
        if not has_animations:
            self.animation_list.clear() # Clear the list if no animations
            self.play_button.setEnabled(False) # Disable play button
            self.stop_button.setEnabled(False) # Disable stop button

    def reset_model_controls(self):
        """Resets model display controls to their default values."""
        print("  [UI Panel] Resetting model controls to default...")
        # Temporarily block signals to avoid emitting default values
        self.edges_checkbox.blockSignals(True); self.opacity_slider.blockSignals(True)
        self.point_size_spinbox.blockSignals(True); self.rep_surface_btn.blockSignals(True)
        self.rep_wireframe_btn.blockSignals(True); self.rep_points_btn.blockSignals(True)
        self.color_override_checkbox.blockSignals(True); self.color_override_button.blockSignals(True)

        self.edges_checkbox.setChecked(False)
        self.opacity_slider.setValue(100)
        self.opacity_value_label.setText("100%")
        self.point_size_spinbox.setValue(5.0)
        self.rep_surface_btn.setChecked(True) # Default is Surface
        self.color_override_checkbox.setChecked(False)
        self._override_color_internal = None
        self._update_color_button_visual(None) # Reset button appearance

        # Unblock signals
        self.edges_checkbox.blockSignals(False); self.opacity_slider.blockSignals(False)
        self.point_size_spinbox.blockSignals(False); self.rep_surface_btn.blockSignals(False)
        self.rep_wireframe_btn.blockSignals(False); self.rep_points_btn.blockSignals(False)
        self.color_override_checkbox.blockSignals(False); self.color_override_button.blockSignals(False)

    def update_controls_from_state(self, actor_settings):
        """Adjusts the UI controls in the panel based on loaded actor settings."""
        if not actor_settings:
            print("[UI Panel] Update controls called with no settings, resetting.")
            self.reset_model_controls()
            return

        print("  [UI Panel] Updating controls from loaded actor state...")
        # Temporarily block signals to prevent feedback loops during update
        all_widgets = self.findChildren(QWidget)
        # original_signals_state = {w: w.signalsBlocked() for w in all_widgets} # Can be used to restore state
        for w in all_widgets: w.blockSignals(True)

        try:
            # Model Display
            self.edges_checkbox.setChecked(actor_settings.get('show_edges', False))
            opacity_val = int(actor_settings.get('opacity', 1.0) * 100)
            self.opacity_slider.setValue(opacity_val)
            self.opacity_value_label.setText(f"{opacity_val}%")
            self.point_size_spinbox.setValue(actor_settings.get('point_size', 5.0))

            rep = actor_settings.get('representation', 'surface')
            if rep == 'surface': self.rep_surface_btn.setChecked(True)
            elif rep == 'wireframe': self.rep_wireframe_btn.setChecked(True)
            elif rep == 'points': self.rep_points_btn.setChecked(True)

            # Color Override
            override_clr_rgb = actor_settings.get('color') # Expects (r,g,b) 0-1 tuple or None
            is_override = override_clr_rgb is not None
            self.color_override_checkbox.setChecked(is_override)
            if is_override:
                self._override_color_internal = QColor.fromRgbF(*override_clr_rgb)
                self._update_color_button_visual(self._override_color_internal)
            else:
                self._override_color_internal = None
                self._update_color_button_visual(None)
            self.color_override_button.setEnabled(is_override)

            # Texture Visibility checkboxes (based on 'active_texture_maps' set)
            active_textures = actor_settings.get('active_texture_maps', set())
            for tex_type, widgets in self._texture_widgets.items():
                 widgets['checkbox'].setChecked(tex_type in active_textures)

            # Note: View settings (Axes, Grid, Background, Lighting, HDR) are part of the main window state,
            # not typically stored per actor, so they are not updated here.

        except Exception as e:
            print(f"[ERROR] Failed to update controls from state: {e}")
            traceback.print_exc()
        finally:
            # Restore original signal state
            # for w, state in original_signals_state.items():
            #      w.blockSignals(state)
            # Simpler method: unblock all signals
            for w in all_widgets: w.blockSignals(False)


    def update_texture_slots(self, loaded_pil_textures, active_texture_types):
        """Updates the state of texture UI elements based on loaded textures."""
        self._loaded_textures_cache = loaded_pil_textures # Update the internal cache

        # Enable/disable texture controls based on what was actually loaded
        available_tex_types = loaded_pil_textures.keys()
        self.set_texture_controls_enabled(bool(available_tex_types), available_tex_types)

        # Set the state of checkboxes based on which textures are active
        for tex_type, widgets in self._texture_widgets.items():
             # Block signals to avoid emitting a signal when updating
             widgets['checkbox'].blockSignals(True)
             # Determine if the checkbox should be checked
             # It should be checked if the texture is available AND active
             should_be_checked = tex_type in available_tex_types and tex_type in active_texture_types
             widgets['checkbox'].setChecked(should_be_checked)
             # Unblock signals
             widgets['checkbox'].blockSignals(False)

             # Enable/disable the preview button based on PIL image availability
             widgets['view_btn'].setEnabled(tex_type in loaded_pil_textures and PILLOW_AVAILABLE)
             if not PILLOW_AVAILABLE:
                  widgets['view_btn'].setToolTip("Requires 'Pillow' library for preview")
             elif tex_type not in loaded_pil_textures:
                  widgets['view_btn'].setToolTip(f"No image data loaded for {widgets['label'].text()}")
             else:
                  widgets['view_btn'].setToolTip(f"Preview the {widgets['label'].text()} texture image")

    def get_texture_from_cache(self, tex_type):
         """Retrieves a PIL image from the internal cache by texture type."""
         # Added this method to make the texture cache accessible for the preview dialog
         return self._loaded_textures_cache.get(tex_type)


    def update_animation_list(self, animation_names):
        """Updates the list of available animations."""
        self.animation_list.clear()
        if animation_names:
            self.animation_list.addItems(animation_names)
            self.set_skel_anim_controls_enabled(has_skeleton=self.skeleton_checkbox.isEnabled(), has_animations=True)
            # Enable play button if an item is selected
            self.animation_list.currentItemChanged.connect(lambda current, previous: self.play_button.setEnabled(current is not None))
            self.play_button.setEnabled(self.animation_list.currentItem() is not None) # Initial state
        else:
            self.set_skel_anim_controls_enabled(has_skeleton=self.skeleton_checkbox.isEnabled(), has_animations=False)


# ==================================================
#           Main Application Window Class
# ==================================================
class ProfessionalViewerMainWindow(QMainWindow):
    """Main application window integrating the PyVista plotter and control panel."""

    # Default settings structure for a newly loaded actor/mesh
    DEFAULT_ACTOR_SETTINGS = {
        'name': 'default_actor',        # Unique name for the actor
        'representation': 'surface',    # 'surface', 'wireframe', 'points'
        'show_edges': False,            # Edge visibility overlay
        'opacity': 1.0,                 # Actor opacity (0.0 - 1.0)
        'point_size': 5.0,              # Size for 'points' representation
        'color': None,                  # Color override (r,g,b tuple) 0-1, or None
        'texture_maps': {},             # Dictionary {tex_type: pv.Texture}
        'active_texture_maps': set(),   # Set of active texture types (e.g., {TEX_BASE_COLOR})
        'uv_coords': None,              # Numpy array of UV coordinates
        'has_texture': False,           # Flag indicating if any texture was loaded
        'has_vertex_colors': False,     # Flag indicating if vertex colors are present
        'is_polydata': False,           # Is the base mesh PolyData (required for textures)?
        'original_scalars_info': None,  # Name of original active scalars (if overridden)
        'skeleton_actor': None          # PyVista actor for the skeleton (placeholder)
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        print("[Main Window] Initializing...")
        self.current_file_path = None
        self.current_actors_info = [] # List to store {'actor': pv.Actor, 'settings': dict, 'mesh': pv.DataSet}
        self.loaded_hdr_texture = None # Stores the loaded PyVista HDR texture object
        self.scene_graph = None # Stores the loaded Trimesh scene (if applicable)
        self.animations = [] # Stores a list of animation names found

        # --- UI Component Creation ---
        self._setup_main_window_properties()
        self._create_central_widget_and_plotter()
        self._create_control_panel_dock_widget() # Creates self.control_panel_widget
        self._create_actions()
        self._connect_control_panel_signals() # Connect signals from the control panel
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self._apply_initial_plotter_settings() # Set background, axes, etc.

        # --- Settings ---
        self._settings = QSettings(ORG_NAME, APP_NAME)
        self._last_dir = self._settings.value("lastDirectory", os.path.expanduser("~"))
        print(f"  [Settings] Initial last directory: {self._last_dir}")
        self._load_window_settings() # Load window state and settings

        # Set initial UI state (most controls disabled)
        self.update_ui_state(model_loaded=False)
        print("[Main Window] Initialization complete.")
        self.status_bar.showMessage(f"{APP_NAME} Ready. Use File > Open to load a model.", 5000)

    # --- UI Setup Functions ---
    def _setup_main_window_properties(self):
        """Sets up basic window properties like title, size, docking."""
        self.setWindowTitle(APP_NAME)
        self.setGeometry(50, 50, 1600, 1000) # Initial position and size
        self.setMinimumSize(900, 700)
        self.setWindowIcon(load_icon("cube.svg")) # Set application icon
        # Allow dock widgets to be nested and tabbed
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks |
                            QMainWindow.DockOption.AllowTabbedDocks |
                            QMainWindow.DockOption.AnimatedDocks)

    def _create_central_widget_and_plotter(self):
        """Creates the main plotting area using PyVistaQt."""
        print("  [Main Window] Creating central widget and PyVista plotter...")
        self.central_frame = QWidget()
        self.main_layout = QVBoxLayout(self.central_frame)
        self.main_layout.setContentsMargins(0, 0, 0, 0) # No margins around the plotter

        if not PYVISTAQT_AVAILABLE:
            # This shouldn't happen due to the initial check, but as a fallback:
            error_label = QLabel("FATAL ERROR: pyvistaqt is required.\nPlease install it and restart.")
            error_label.setAlignment(Qt.AlignCenter)
            self.main_layout.addWidget(error_label)
            self.setCentralWidget(self.central_frame)
            QMessageBox.critical(self, "Initialization Error", "pyvistaqt is missing.")
            # Consider disabling further UI setup if plotter fails
            self.plotter = None
            return

        # Create the QtInteractor
        self.plotter = QtInteractor(parent=self.central_frame, auto_update=True)
        self.main_layout.addWidget(self.plotter.interactor) # Add the plotter widget
        self.setCentralWidget(self.central_frame)
        print("  [Main Window] Plotter created successfully.")

    def _create_control_panel_dock_widget(self):
        """Creates the dockable widget holding the ControlPanel."""
        print("  [Main Window] Creating control panel dock widget...")
        self.control_dock = QDockWidget("Controls", self)
        self.control_dock.setObjectName("ControlDock") # For saving/restoring state
        self.control_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        # Create an instance of the ControlPanel
        self.control_panel_widget = ControlPanel(self.control_dock)
        self.control_dock.setWidget(self.control_panel_widget)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.control_dock) # Add the dock panel to the right side

    def _create_actions(self):
        """Creates QActions for menus and toolbars."""
        print("  [Main Window] Creating actions...")
        # File Actions
        self.action_open = QAction(load_icon("file-plus.svg"), "&Open Model...", self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open.setStatusTip("Open a 3D model file")
        self.action_open.triggered.connect(self.on_open_file)

        self.action_close_model = QAction(load_icon("file-minus.svg"), "&Close Model", self)
        self.action_close_model.setStatusTip("Close the currently loaded model")
        self.action_close_model.triggered.connect(self.on_close_model)
        self.action_close_model.setEnabled(False) # Enabled when a model is loaded

        self.action_load_hdr = QAction(load_icon("image.svg"), "Load &HDR Environment...", self)
        self.action_load_hdr.setStatusTip("Load an HDR or EXR file for image-based lighting")
        self.action_load_hdr.triggered.connect(self.on_load_hdr)
        self.action_load_hdr.setEnabled(IMAGEIO_AVAILABLE)

        self.action_clear_hdr = QAction(load_icon("x-circle.svg"), "Clear HDR &Environment", self)
        self.action_clear_hdr.setStatusTip("Remove the loaded HDR environment")
        self.action_clear_hdr.triggered.connect(self.on_clear_hdr)
        self.action_clear_hdr.setEnabled(False) # Enabled when HDR is loaded

        self.action_exit = QAction(load_icon("log-out.svg"), "E&xit", self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_exit.setStatusTip("Exit the application")
        self.action_exit.triggered.connect(self.close) # Trigger the window close event

        # View Actions
        self.action_toggle_control_panel = self.control_dock.toggleViewAction()
        self.action_toggle_control_panel.setText("&Control Panel")
        self.action_toggle_control_panel.setIcon(load_icon("sidebar.svg"))
        self.action_toggle_control_panel.setStatusTip("Show/Hide the control panel")

        # Create a QAction for toggling Axes visibility
        self.action_toggle_axes = QAction("Show &Axes", self) # No icon needed, the checkbox has one
        self.action_toggle_axes.setCheckable(True) # Make the action checkable
        self.action_toggle_axes.setStatusTip("Toggle visibility of the coordinate axes")
        # Set initial state based on the default value of the control panel checkbox
        if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'axes_checkbox'):
             self.action_toggle_axes.setChecked(self.control_panel_widget.axes_checkbox.isChecked())
        else:
             self.action_toggle_axes.setChecked(True) # Default if panel not available

        # Connect the action's toggled signal to the slot that handles axes visibility
        self.action_toggle_axes.toggled.connect(self.on_toggle_axes) # Connect to MainWindow slot

        # Sync the action's checked state with the control panel's checkbox
        if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'axes_checkbox'):
             self.control_panel_widget.axes_checkbox.toggled.connect(self.action_toggle_axes.setChecked)
             self.action_toggle_axes.toggled.connect(self.control_panel_widget.axes_checkbox.setChecked) # Action controls checkbox

        # Create a QAction for toggling Grid visibility
        self.action_toggle_grid = QAction(load_icon("grid.svg"), "Show &Grid", self)
        self.action_toggle_grid.setCheckable(True) # Make the action checkable
        self.action_toggle_grid.setStatusTip("Toggle the ground grid plane")
        # Set initial state based on the default value of the control panel checkbox
        if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'grid_checkbox'):
             self.action_toggle_grid.setChecked(self.control_panel_widget.grid_checkbox.isChecked())
        else:
             self.action_toggle_grid.setChecked(False) # Default if panel not available

        # Connect the action's toggled signal to the slot that handles grid visibility
        self.action_toggle_grid.toggled.connect(self.on_toggle_grid) # Connect to MainWindow slot

        # Sync the action's checked state with the control panel's checkbox
        if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'grid_checkbox'):
             self.control_panel_widget.grid_checkbox.toggled.connect(self.action_toggle_grid.setChecked)
             self.action_toggle_grid.toggled.connect(self.control_panel_widget.grid_checkbox.setChecked) # Action controls checkbox


        # Help Actions
        self.action_about = QAction(load_icon("info.svg"), "&About...", self)
        self.action_about.setStatusTip(f"Show information about {APP_NAME}")
        self.action_about.triggered.connect(self.on_about)

        self.action_about_qt = QAction(load_icon("help-circle.svg"), "About &Qt...", self)
        self.action_about_qt.setStatusTip("Show information about the Qt framework")
        self.action_about_qt.triggered.connect(QApplication.aboutQt)

    def _connect_control_panel_signals(self):
        """Connects signals from the ControlPanel to slots in this MainWindow."""
        if not hasattr(self, 'control_panel_widget'): return
        print("  [Main Window] Connecting control panel signals to main window slots...")
        panel = self.control_panel_widget
        # View Signals
        panel.reset_camera_signal.connect(self.on_reset_camera)
        # panel.toggle_axes_signal.connect(self.on_toggle_axes) # This connection is now handled in _create_actions for sync
        # panel.toggle_grid_signal.connect(self.on_toggle_grid) # This connection is now handled in _create_actions for sync
        panel.change_bgcolor_signal.connect(self.on_change_bgcolor)
        panel.lighting_preset_changed_signal.connect(self.on_lighting_preset_changed)
        panel.load_hdr_signal.connect(self.on_load_hdr) # Connect HDR load from panel button
        panel.clear_hdr_signal.connect(self.on_clear_hdr) # Connect HDR clear from panel button
        # Model Signals
        panel.toggle_edges_signal.connect(self.on_toggle_edges)
        panel.representation_changed_signal.connect(self.on_representation_changed)
        panel.opacity_changed_signal.connect(self.on_opacity_changed)
        panel.point_size_changed_signal.connect(self.on_point_size_changed)
        panel.color_override_signal.connect(self.on_color_override)
        # Texture Signals
        panel.texture_visibility_changed_signal.connect(self.on_texture_visibility_changed)
        panel.view_texture_signal.connect(self.on_view_texture) # Connect texture view signal
        # Skeleton/Animation Signals (Placeholders)
        panel.toggle_skeleton_signal.connect(self.on_toggle_skeleton)
        panel.play_animation_signal.connect(self.on_play_animation)
        panel.stop_animation_signal.connect(self.on_stop_animation)


    def _create_menus(self):
        """Creates the main menu bar and populates it with actions."""
        print("  [Main Window] Creating menus...")
        menu_bar = self.menuBar()

        # File Menu
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_close_model)
        file_menu.addSeparator()
        file_menu.addAction(self.action_load_hdr)
        file_menu.addAction(self.action_clear_hdr)
        file_menu.addSeparator()
        file_menu.addAction(self.action_exit)

        # View Menu
        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self.action_toggle_control_panel)
        view_menu.addSeparator()
        # Add actions corresponding to the checkboxes in the control panel
        # Use the custom actions created in _create_actions
        view_menu.addAction(self.action_toggle_axes) # Add the new axes toggle action
        view_menu.addAction(self.action_toggle_grid) # Use the action linked to the grid checkbox
        # Add other view options here if needed (e.g., toggle perspective/orthographic)

        # Help Menu
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.action_about)
        help_menu.addAction(self.action_about_qt)

    def _create_toolbar(self):
        """Creates the main application toolbar."""
        print("  [Main Window] Creating toolbar...")
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("MainToolbar") # For saving/restoring state
        toolbar.setIconSize(QSize(22, 22)) # Adjust icon size as needed

        toolbar.addAction(self.action_open)
        toolbar.addAction(self.action_close_model)
        toolbar.addSeparator()
        # Add a dedicated Reset Camera button to the toolbar
        reset_cam_action = QAction(load_icon("view-3d.svg"), "Reset Camera", self)
        reset_cam_action.setStatusTip("Reset camera view")
        reset_cam_action.triggered.connect(self.on_reset_camera)
        toolbar.addAction(reset_cam_action)
        toolbar.addAction(self.action_toggle_axes) # Add axes toggle to toolbar
        toolbar.addAction(self.action_toggle_grid) # Add grid toggle to toolbar as well
        toolbar.addSeparator()
        toolbar.addAction(self.action_toggle_control_panel) # Toggle panel visibility

    def _create_status_bar(self):
        """Creates the status bar at the bottom of the window."""
        print("  [Main Window] Creating status bar...")
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Welcome!", 2000) # Initial message

    def _apply_initial_plotter_settings(self):
        """Sets up the initial state of the PyVista plotter."""
        if not self.plotter:
             print("[WARN] Plotter not available, skipping initial settings.")
             return
        print("  [Main Window] Applying initial plotter settings...")
        try:
            # Add coordinate axes widget
            # Initial state based on the default value of the control panel checkbox (which is True)
            if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'axes_checkbox'):
                 if self.control_panel_widget.axes_checkbox.isChecked():
                      self.plotter.show_axes()
                 else:
                      self.plotter.hide_axes()
            else:
                 # Default to showing axes if the panel is not available
                 self.plotter.show_axes()

            # Set initial background color
            self.plotter.set_background("lightsteelblue") # Or choose another default

            # Enable anti-aliasing (MSAA often gives good quality/performance)
            self.plotter.enable_anti_aliasing('msaa')

            # Enable a basic light kit
            try:
                 # Use renderer to add lights
                 self.plotter.renderer.RemoveAllLights() # Clear any default lights first
                 self.plotter.enable_lightkit() # This adds lights to the renderer
                 print("   Used plotter.enable_lightkit()")
            except Exception as e:
                 print(f"[WARN] Failed to enable light kit: {e}")
                 # Fallback to manual lights if lightkit fails
                 # Note: Manual lights also need to be added to the renderer
                 self._apply_light_preset("Default Kit") # Apply default lights manually


            # Add a default ground plane/grid (optional, hidden initially)
            # The grid toggle in the UI uses plotter.show_grid() / remove_bounds_axes()
            # We don't need to add a persistent grid actor here unless we want a different type of grid.
            # self.plotter.add_grid(render=False) # Using show_grid() / remove_bounds_axes() via UI instead

            print("  [Main Window] Initial plotter settings applied.")
        except Exception as e:
            print(f"[ERROR] Failed to apply initial plotter settings: {e}")
            QMessageBox.warning(self, "Plotter Setup Error", f"Could not configure plotter defaults:\n{e}")


    # --- Slots (Connected to Actions and Control Panel Signals) ---

    @Slot()
    def on_open_file(self):
        """Handles the File > Open action."""
        print("-> Action: Open File")
        # Define file filters
        # Prioritize GLB/GLTF, then others. FBX is often problematic and requires pyassimp.
        file_filter = (
            "Supported 3D Models (*.glb *.gltf *.obj *.stl *.ply *.vtk *.vtp *.vts *.fbx);;"
            "GLTF Binary (*.glb);;"
            "GLTF Text (*.gltf);;"
            "Wavefront OBJ (*.obj);;"
            "Stereolithography (*.stl);;"
            "Stanford PLY (*.ply);;"
            f"FBX (*.fbx) ({'Requires pyassimp' if not PYASSIMP_AVAILABLE else 'pyassimp available'});;" # Note FBX dependency
            "VTK Legacy (*.vtk);;"
            "VTK PolyData (*.vtp);;"
            "VTK StructuredGrid (*.vts);;"
            "All Files (*.*)"
        )
        # Get the file path from the user
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open 3D Model",
            self._last_dir, # Start directory (can be saved/restored)
            file_filter
        )
        if file_path:
            # If a file was selected, attempt to load it
            self._last_dir = os.path.dirname(file_path) # Update last directory
            self._load_model_file(file_path)
        else:
            self.status_bar.showMessage("File open cancelled.", 3000)

    @Slot()
    def on_close_model(self):
        """Handles closing the current model and resetting the view."""
        print("-> Action: Close Model")
        if not self.current_actors_info:
            print("   No model currently loaded.")
            return # Nothing to close

        print(f"   Removing {len(self.current_actors_info)} actors and associated data...")
        actors_to_remove = []
        for info in self.current_actors_info:
            if info.get('actor'):
                actors_to_remove.append(info['actor'])
            # Include the skeleton actor if it exists
            if info.get('settings', {}).get('skeleton_actor'):
                actors_to_remove.append(info['settings']['skeleton_actor'])

        if self.plotter and actors_to_remove:
            try:
                self.plotter.remove_actor(actors_to_remove, render=False) # Remove all at once
                print(f"   Removed {len(actors_to_remove)} PyVista actors.")
            except Exception as e:
                print(f"[WARN] Error during actor removal: {e}")

        # Clear internal state
        self.current_actors_info = []
        self.current_file_path = None
        self.scene_graph = None
        self.animations = []
        # Optionally clear HDR as well if it was loaded specifically for this model.
        # For now, keep HDR unless explicitly cleared by the user.
        # self.on_clear_hdr()

        print("   Internal state cleared.")
        # Update UI elements to reflect the closed state
        self.update_ui_state(model_loaded=False)
        self.setWindowTitle(APP_NAME) # Reset window title
        self.status_bar.showMessage("Model closed.", 5000)
        if self.plotter:
            self.plotter.render() # Update the view

    # --- View Control Slots ---
    @Slot()
    def on_reset_camera(self):
        """Resets the camera position to fit the loaded actors."""
        if not self.plotter: return
        if not self.current_actors_info:
             self.status_bar.showMessage("No model loaded to reset view.", 2000)
             return
        print("-> Action: Reset Camera")
        try:
            self.plotter.reset_camera()
            self.status_bar.showMessage("Camera view reset.", 2000)
        except Exception as e:
            print(f"[ERROR] Failed to reset camera: {e}")
            self.status_bar.showMessage("Camera reset failed.", 3000)


    @Slot(bool)
    def on_toggle_axes(self, checked):
        """Toggles the visibility of the coordinate axes widget."""
        if not self.plotter: return
        print(f"-> Action: Toggle Axes ({checked})")
        try:
            if checked:
                self.plotter.show_axes()
            else:
                self.plotter.hide_axes()
            self.status_bar.showMessage(f"Axes {'shown' if checked else 'hidden'}.", 2000)
        except Exception as e:
            print(f"[ERROR] Failed to toggle axes: {e}")
            # Optionally revert the state of the checkbox in the panel if available
            if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'axes_checkbox'):
                 cb = self.control_panel_widget.axes_checkbox
                 cb.blockSignals(True)
                 cb.setChecked(not checked)
                 cb.blockSignals(False)
            # Revert the action state
            self.action_toggle_axes.blockSignals(True)
            self.action_toggle_axes.setChecked(not checked)
            self.action_toggle_axes.blockSignals(False)


    @Slot(bool)
    def on_toggle_grid(self, checked):
        """Toggles the visibility of the ground grid."""
        if not self.plotter: return
        print(f"-> Action: Toggle Grid ({checked})")
        try:
            if checked:
                 # Customize grid appearance here if needed (bounds, color, etc.)
                 self.plotter.show_grid() # Use PyVista's built-in grid
                 print("   Grid shown.")
            else:
                 # plotter.show_grid(False) doesn't exist, remove the grid actor
                 self.plotter.remove_bounds_axes() # This removes the actor created by show_grid
                 print("   Grid hidden (removed bounds axes).")
            self.status_bar.showMessage(f"Grid {'shown' if checked else 'hidden'}.", 2000)
        except AttributeError:
             print("[WARN] Plotter might not have 'show_grid' or 'remove_bounds_axes'. Grid toggle may fail.")
             QMessageBox.warning(self, "Grid Error", "Could not toggle grid. Plotter methods might be missing.")
             # Revert the state of the checkbox in the panel if available
             if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'grid_checkbox'):
                 cb = self.control_panel_widget.grid_checkbox
                 cb.blockSignals(True); cb.setChecked(not checked); cb.blockSignals(False)
             # Revert the action state
             self.action_toggle_grid.blockSignals(True); self.action_toggle_grid.setChecked(not checked); self.action_toggle_grid.blockSignals(False)
        except Exception as e:
            print(f"[ERROR] Failed to toggle grid: {e}")
            QMessageBox.warning(self, "Grid Error", f"Could not toggle grid:\n{e}")
            # Revert the state of the checkbox in the panel if available
            if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'grid_checkbox'):
                 cb = self.control_panel_widget.grid_checkbox
                 cb.blockSignals(True); cb.setChecked(not checked); cb.blockSignals(False)
            # Revert the action state
            self.action_toggle_grid.blockSignals(True); self.action_toggle_grid.setChecked(not checked); self.action_toggle_grid.blockSignals(False)


    @Slot()
    def on_change_bgcolor(self):
        """Opens a color dialog to change the background color."""
        if not self.plotter: return
        print("-> Action: Change Background Color")
        try:
            # Get the current background color from the plotter
            current_pv_color = self.plotter.background_color
            # Convert PyVista color (tuple/list/str) to QColor
            current_q_color = QColor.fromRgbF(*pv.Color(current_pv_color).float_rgb) # Use pv.Color for robust conversion
        except Exception as e:
            print(f"[WARN] Could not get current background color: {e}. Using default gray.")
            current_q_color = Qt.GlobalColor.lightGray

        # Open QColorDialog
        new_q_color = QColorDialog.getColor(current_q_color, self, "Select Background Color")

        if new_q_color.isValid():
            try:
                # Convert QColor back to a format PyVista understands (e.g., name or RGB tuple)
                new_pv_color = new_q_color.name() # Use hex name #RRGGBB
                self.plotter.set_background(new_pv_color)
                print(f"   Background color set to {new_pv_color}")
                self.status_bar.showMessage("Background color updated.", 3000)
            except Exception as e:
                print(f"[ERROR] Failed to set background color: {e}")
                QMessageBox.warning(self, "Background Color Error", f"Could not set background color:\n{e}")
        else:
            print("   Background color change cancelled.")

    @Slot(str)
    def on_lighting_preset_changed(self, preset_name):
        """Applies a selected lighting preset."""
        if not self.plotter: return
        print(f"-> Action: Change Lighting Preset to '{preset_name}'")

        try:
            self._apply_light_preset(preset_name) # Call the new helper method

        except Exception as e:
            print(f"[ERROR] Failed to apply lighting preset '{preset_name}': {e}")
            traceback.print_exc()
            QMessageBox.critical(self, "Lighting Error", f"Could not apply lighting preset:\n{e}")

    def _apply_light_preset(self, preset_name):
        """Helper method to apply a specific lighting preset by managing lights."""
        if not self.plotter or not hasattr(self.plotter, 'renderer'):
             print("[WARN] Plotter or renderer not available, cannot apply lighting preset.")
             return

        # Remove all existing lights first to ensure a clean slate for the preset
        try:
            # Access lights via the renderer
            self.plotter.renderer.RemoveAllLights()
            print("   Cleared existing lights.")
        except Exception as e:
            print(f"[WARN] Could not remove existing lights via renderer: {e}")
            # Continue anyway

        is_env_preset = "Environment" in preset_name

        if is_env_preset:
            if self.loaded_hdr_texture:
                print("   Applying Environment (HDR) lighting.")
                # Add the environment texture as a light source
                # PyVista's add_environment_texture adds it to the renderer
                self.plotter.add_environment_texture(self.loaded_hdr_texture)
                # Ensure no other lights are active if IBL is used, unless desired
                # remove_all_lights was already called
            else:
                print("[WARN] 'Environment (HDR)' selected, but no HDR loaded. Falling back to Default Kit.")
                QMessageBox.warning(self, "Lighting Preset", "Please load an HDR file first to use Environment lighting.")
                # Search for the combo box and reset it (prevent infinite loop)
                if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'lighting_combo'):
                    combo = self.control_panel_widget.lighting_combo
                    combo.blockSignals(True)
                    combo.setCurrentText("Default Kit")
                    combo.blockSignals(False)
                # Apply the fallback preset
                self._apply_light_preset("Default Kit") # Recursive call, but should hit base case
                return # Exit this call to prevent applying other lights

        elif preset_name == "Default Kit":
            print("   Applying Default Light Kit (manual lights or enable_lightkit).")
            # Manually add lights that simulate the default kit or use enable_lightkit
            try:
                 # This method adds lights to the renderer
                 self.plotter.enable_lightkit()
                 print("   Used plotter.enable_lightkit()")
            except Exception as e:
                 print(f"[WARN] enable_lightkit failed: {e}. Adding manual lights to renderer.")
                 # Add lights directly to the renderer if enable_lightkit fails
                 # Need to import vtk if adding manual lights this way
                 try:
                     import vtk
                     light1 = vtk.vtkLight()
                     light1.SetLightTypeToHeadlight()
                     self.plotter.renderer.AddLight(light1) # Add headlight

                     light2 = vtk.vtkLight()
                     light2.SetLightTypeToSceneLight()
                     light2.SetPosition(10, 10, 10)
                     light2.SetIntensity(0.5)
                     self.plotter.renderer.AddLight(light2) # Add another scene light
                 except ImportError:
                     print("[ERROR] VTK not available to add manual lights.")
                     QMessageBox.critical(self, "Lighting Error", "VTK library is required for manual lighting but not found.")


        elif preset_name == "None":
            print("   Removing all lights.")
            # remove_all_lights was already called at the start via renderer
            pass # No lights needed

        elif preset_name == "Cad":
            print("   Applying CAD lighting preset (manual lights to renderer).")
            try:
                import vtk
                # Add specific lights for a CAD-like look directly to the renderer
                light1 = vtk.vtkLight()
                light1.SetLightTypeToSceneLight()
                light1.SetPosition(10, 10, 10)
                light1.SetIntensity(0.8)
                self.plotter.renderer.AddLight(light1)

                light2 = vtk.vtkLight()
                light2.SetLightTypeToSceneLight()
                light2.SetPosition(-10, 10, 0)
                light2.SetIntensity(0.6)
                self.plotter.renderer.AddLight(light2)
            except ImportError:
                print("[ERROR] VTK not available to add manual lights.")
                QMessageBox.critical(self, "Lighting Error", "VTK library is required for manual lighting but not found.")


        elif preset_name == "Bright":
            print("   Applying Bright lighting preset (manual lights to renderer).")
            try:
                import vtk
                # Add specific lights for a brighter look directly to the renderer
                light1 = vtk.vtkLight()
                light1.SetLightTypeToSceneLight()
                light1.SetPosition(0, 0, 15)
                light1.SetIntensity(1.0)
                self.plotter.renderer.AddLight(light1)

                light2 = vtk.vtkLight()
                light2.SetLightTypeToSceneLight()
                light2.SetPosition(0, 0, -15)
                light2.SetIntensity(0.8)
                self.plotter.renderer.AddLight(light2)
            except ImportError:
                print("[ERROR] VTK not available to add manual lights.")
                QMessageBox.critical(self, "Lighting Error", "VTK library is required for manual lighting but not found.")


        # Render the scene after applying the lights
        self.plotter.render()
        self.status_bar.showMessage(f"Lighting preset: {preset_name}", 3000)


    @Slot()
    def on_load_hdr(self):
        """Loads an HDR image for environment lighting."""
        if not self.plotter: return
        if not IMAGEIO_AVAILABLE:
            QMessageBox.warning(self, "Missing Library", "Loading HDR environments requires the 'imageio' library.")
            return
        print("-> Action: Load HDR Environment")
        # Define file filter for HDR formats
        hdr_filter = "HDR Images (*.hdr *.exr);;All Files (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(self, "Load HDR Environment", self._last_dir, hdr_filter)

        if file_path:
            self._last_dir = os.path.dirname(file_path) # Update last directory
            self.status_bar.showMessage(f"Loading HDR: {os.path.basename(file_path)}...")
            QApplication.processEvents() # Keep UI responsive during load attempt

            try:
                # Read HDR image using imageio
                # imageio loads as numpy array
                hdr_image_data = iio.imread(file_path)
                print(f"   HDR image loaded, shape: {hdr_image_data.shape}, dtype: {hdr_image_data.dtype}")

                # Create a PyVista texture object
                self.loaded_hdr_texture = pv.Texture(hdr_image_data)

                # Add it to the plotter as an environment texture
                # This also acts as a light source for Image-Based Lighting (IBL)
                # This method adds a vtkLight to the renderer with type 'EnvironmentLight'
                self.plotter.add_environment_texture(self.loaded_hdr_texture)
                print("   HDR environment texture added to plotter.")

                # Ensure other lights are off when using environment lighting
                if hasattr(self.plotter, 'renderer'):
                     # Remove all lights added by enable_lightkit or manual presets
                     self.plotter.renderer.RemoveAllLights()
                     # The add_environment_texture call above adds the necessary environment light
                     # We might need to re-add the environment light if RemoveAllLights removed it
                     # Check if the environment light is still there, if not, re-add
                     env_light_found = False
                     # Need to import vtk to check light types
                     try:
                         import vtk
                         lights = self.plotter.renderer.GetLights()
                         if lights:
                             lights.InitTraversal()
                             light = lights.GetNextItem()
                             while light:
                                  if hasattr(light, 'GetLightType') and light.GetLightType() == vtk.VTK_LIGHT_TYPE_ENVIRONMENT:
                                       env_light_found = True
                                       break
                                  light = lights.GetNextItem()
                     except ImportError:
                         print("[WARN] VTK not available to check light types during HDR clear.")


                     if not env_light_found:
                          print("   Environment light removed unexpectedly, re-adding.")
                          self.plotter.add_environment_texture(self.loaded_hdr_texture)


                # Optional: switch lighting preset to Environment if not already selected
                if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'lighting_combo'):
                    combo = self.control_panel_widget.lighting_combo
                    if "Environment" not in combo.currentText():
                        print("   Switching lighting preset to Environment (HDR).")
                        combo.blockSignals(True)
                        combo.setCurrentText("Environment (HDR)")
                        combo.blockSignals(False)
                        # The preset change will now use the loaded HDR texture

                self.plotter.render() # Update the view
                self.status_bar.showMessage(f"HDR Loaded: {os.path.basename(file_path)}", 5000)
                # Enable 'Clear HDR' button/action
                if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'clear_hdr_button'):
                    self.control_panel_widget.clear_hdr_button.setEnabled(True)
                self.action_clear_hdr.setEnabled(True)

            except FileNotFoundError:
                 self._handle_load_error(f"HDR file not found: {file_path}", file_path, is_hdr=True)
            except Exception as e:
                 self._handle_load_error(e, file_path, is_hdr=True)
        else:
            self.status_bar.showMessage("HDR load cancelled.", 3000)

    @Slot()
    def on_clear_hdr(self):
        """Removes the loaded HDR environment texture."""
        if not self.plotter: return
        if not self.loaded_hdr_texture:
            print("-> Action: Clear HDR (No HDR currently loaded)")
            self.status_bar.showMessage("No HDR environment to clear.", 2000)
            return

        print("-> Action: Clear HDR Environment")
        try:
            # Removing the environment texture also removes the associated light
            self.plotter.remove_environment_texture()
            self.loaded_hdr_texture = None # Clear the stored texture object
            print("   HDR environment texture removed.")

            # Revert to default lighting
            self._apply_light_preset("Default Kit")

            # Optional: revert lighting preset combo box
            if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'lighting_combo'):
                combo = self.control_panel_widget.lighting_combo
                if "Environment" in combo.currentText():
                     print("   Reverting lighting preset combo box to Default Kit.")
                     combo.blockSignals(True)
                     combo.setCurrentText("Default Kit")
                     combo.blockSignals(False)


            self.plotter.render()
            self.status_bar.showMessage("HDR environment cleared.", 3000)
            # Disable 'Clear HDR' button/action
            if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'clear_hdr_button'):
                self.control_panel_widget.clear_hdr_button.setEnabled(False)
            self.action_clear_hdr.setEnabled(False)

        except Exception as e:
            print(f"[ERROR] Failed to clear HDR environment: {e}")
            QMessageBox.warning(self, "HDR Error", f"Could not clear HDR environment:\n{e}")

    # --- Model Control Slots ---

    def _apply_actor_property(self, prop_name, value, status_msg, render=False):
        """Helper function to apply a property change to the properties of all current actors."""
        if not self.current_actors_info:
            # print(f"[WARN] Cannot apply property '{prop_name}', no actors loaded.")
            return
        if not self.plotter: return

        print(f"-> Applying Actor Property: {prop_name} = {value}")
        change_applied = False
        try:
            for info in self.current_actors_info:
                actor = info.get('actor')
                settings = info.get('settings') # Get the settings dict for this actor

                if actor and hasattr(actor, 'prop') and actor.prop:
                    # Check if the property exists on the actor's property
                    if hasattr(actor.prop, prop_name):
                        # Get the current value to avoid unnecessary renders if value is the same
                        current_value = getattr(actor.prop, prop_name)
                        # Special handling for float comparisons
                        if isinstance(value, float) and isinstance(current_value, float):
                             if abs(current_value - value) < 1e-6: # Use a tolerance for float comparison
                                  continue # Skip if values are effectively the same
                        elif current_value == value:
                            continue # Skip if value is the same

                        # Use setattr to set the property on the VTK property object
                        setattr(actor.prop, prop_name, value)
                        # Update the stored settings as well
                        if settings:
                            settings[prop_name] = value
                        change_applied = True
                    else:
                        print(f"[WARN] Actor '{settings.get('name', 'Unknown')}' prop has no attribute '{prop_name}'")
                elif actor:
                     print(f"[WARN] Actor '{settings.get('name', 'Unknown')}' has no 'prop' attribute.")

            if change_applied:
                if render:
                    self.plotter.render()
                if status_msg:
                    self.status_bar.showMessage(status_msg, 2000)
            # else:
            #     print(f"   No change applied for property '{prop_name}'.")

        except Exception as e:
            print(f"[ERROR] Failed setting actor property '{prop_name}' to '{value}': {e}")
            traceback.print_exc()
            self.status_bar.showMessage(f"Error setting {prop_name}.", 3000)

    # Connect simple property changes directly to the helper function
    @Slot(bool)
    def on_toggle_edges(self, checked):
        # PyVista actor property is 'show_edges', VTK property is 'EdgeVisibility'
        # We store 'show_edges' in settings but set 'EdgeVisibility' on the VTK prop
        self._apply_actor_property('EdgeVisibility', checked, f"Edges {'On' if checked else 'Off'}", render=True)
        # Update the internal setting name
        if self.current_actors_info:
             for info in self.current_actors_info:
                  info['settings']['show_edges'] = checked


    @Slot(str)
    def on_representation_changed(self, style):
        # Map the style string ('surface', 'wireframe', 'points') to PyVista representation enum/value if needed
        # For actor.prop.SetRepresentation, strings usually work directly.
        # VTK representation constants: 0=Points, 1=Wireframe, 2=Surface
        representation_map = {'points': 0, 'wireframe': 1, 'surface': 2}
        vtk_representation = representation_map.get(style, 2) # Default to Surface (2)

        if self.current_actors_info:
            change_applied = False
            try:
                for info in self.current_actors_info:
                    actor = info.get('actor')
                    settings = info.get('settings')
                    if actor and hasattr(actor, 'prop') and actor.prop:
                        if actor.prop.GetRepresentation() != vtk_representation:
                            actor.prop.SetRepresentation(vtk_representation)
                            if settings:
                                settings['representation'] = style # Store the string name
                            change_applied = True
                    # Update point size visibility based on style
                    if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'point_size_spinbox'):
                         self.control_panel_widget.point_size_spinbox.setEnabled(style == 'points')

                if change_applied:
                    self.plotter.render()
                    self.status_bar.showMessage(f"Representation: {style.capitalize()}", 2000)
                    print(f"-> Applied Representation: {style} (VTK: {vtk_representation})")
            except Exception as e:
                print(f"[ERROR] Failed to change model representation: {e}")
                traceback.print_exc()
                self.status_bar.showMessage("Error changing representation", 3000)
        else:
            print("[App] No model loaded to change representation.")


    @Slot(int)
    def on_opacity_changed(self, value_percent):
        opacity_float = max(0.0, min(1.0, value_percent / 100.0))
        # PyVista actor property is 'opacity'
        self._apply_actor_property('opacity', opacity_float, f"Opacity: {value_percent}%", render=True) # Opacity needs rendering
        # Note: _apply_actor_property already updates settings['opacity']


    @Slot(float)
    def on_point_size_changed(self, size):
        # PyVista actor property is 'point_size'
        self._apply_actor_property('point_size', size, f"Point Size: {size:.1f}", render=True) # Point size needs rendering
        # Note: _apply_actor_property already updates settings['point_size']


    @Slot(object) # Expects QColor or None
    def on_color_override(self, q_color):
        """Applies or removes a solid color override."""
        if not self.current_actors_info: return
        if not self.plotter: return

        # Convert QColor (or None) to a PyVista color tuple (r,g,b) 0-1 or None
        # Use pv.Color for robust conversion to float_rgb tuple
        pv_color_rgb = pv.Color(q_color).float_rgb if q_color and q_color.isValid() else None

        status = f"Color override applied" if pv_color_rgb else "Color override removed"
        print(f"-> Action: Color Override {'Set to ' + str(pv_color_rgb) if pv_color_rgb else 'Removed'}")

        try:
            for info in self.current_actors_info:
                actor = info.get('actor')
                settings = info.get('settings')
                mesh = info.get('mesh')
                if not actor or not settings or not mesh: continue

                actor_name = settings.get('name', 'Unknown')

                if pv_color_rgb:
                    # --- Apply Override ---
                    print(f"   Applying override to {actor_name}")
                    # Store original scalars info if we are about to disable scalars
                    # Check if actor currently has scalars visible AND color override is NOT currently active
                    if actor.mapper.scalar_visibility and settings.get('color') is None:
                        settings['original_scalars_info'] = actor.mapper.scalars_name
                        print(f"     Stored original scalars: {settings['original_scalars_info']}")

                    # Disable texture and scalars, apply solid color using actor.color
                    actor.texture = None # Remove texture
                    actor.mapper.scalar_visibility = False # Hide scalars
                    actor.color = pv_color_rgb # Set solid color using PyVista property
                    settings['color'] = pv_color_rgb # Store the override color in settings
                    # Ensure active texture maps set is cleared when overridden
                    settings['active_texture_maps'] = set()


                else:
                    # --- Remove Override ---
                    print(f"   Removing override from {actor_name}")
                    # Reset actor color property to None to allow texture/scalars to take effect
                    actor.color = None
                    settings['color'] = None # Clear the override in settings

                    # --- Attempt to Restore Original Appearance ---
                    restored = False
                    # 1. Check for BaseColor texture + UV coords
                    base_color_tex = settings.get('texture_maps', {}).get(TEX_BASE_COLOR)
                    if settings.get('is_polydata') and base_color_tex is not None and settings.get('uv_coords') is not None:
                        print(f"     Restoring BaseColor texture for {actor_name}")
                        actor.texture = base_color_tex
                        actor.mapper.scalar_visibility = False # Texture takes precedence over scalars
                        settings['active_texture_maps'].add(TEX_BASE_COLOR) # Mark as active again
                        restored = True
                    # 2. Check for stored original scalars
                    elif settings.get('original_scalars_info'):
                        original_scalars = settings['original_scalars_info']
                        print(f"     Restoring original scalars '{original_scalars}' for {actor_name}")
                        # Check if the scalars still exist on the mesh
                        if original_scalars in mesh.point_data or original_scalars in mesh.cell_data:
                             actor.mapper.scalar_visibility = True
                             # Need to re-select the scalar array and mode
                             actor.mapper.SetScalarModeToUsePointFieldData() if original_scalars in mesh.point_data else actor.mapper.SetScalarModeToUseCellFieldData()
                             actor.mapper.SelectColorArray(original_scalars)
                             restored = True
                        else:
                             print(f"[WARN] Original scalars '{original_scalars}' no longer found on mesh.")
                             actor.mapper.scalar_visibility = False # Fallback
                        settings['original_scalars_info'] = None # Clear stored info
                    # 3. Check for any active scalars on the mesh
                    elif mesh.active_scalars is not None:
                         print(f"     Restoring active scalars '{mesh.active_scalars_info.name}' for {actor_name}")
                         actor.mapper.scalar_visibility = True
                         # Need to re-select the scalar array and mode
                         actor.mapper.SetScalarModeToUsePointFieldData() if mesh.active_scalars_info.association == pv.FieldAssociation.POINT else actor.mapper.SetScalarModeToUseCellFieldData()
                         actor.mapper.SelectColorArray(mesh.active_scalars_info.name)
                         restored = True
                    # 4. Fallback: No texture, no scalars - maybe set a default color?
                    else:
                         print(f"     No texture or scalars to restore for {actor_name}. Setting default grey.")
                         actor.mapper.scalar_visibility = False
                         actor.color = 'lightgrey' # Fallback color using PyVista property


                    # If we restored texture, ensure scalar visibility is off
                    if actor.texture is not None:
                        actor.mapper.scalar_visibility = False


            self.plotter.render()
            self.status_bar.showMessage(status, 3000)
            # Update the control panel state to reflect changes (especially texture checkboxes)
            if self.current_actors_info and hasattr(self, 'control_panel_widget'):
                 # Assuming all actors get the same texture/color state for simplicity in this UI
                 # In a multi-actor scene with different materials, this would need refinement.
                 # For now, just update based on the first actor's settings.
                 self.control_panel_widget.update_texture_slots(
                     self.control_panel_widget._loaded_textures_cache, # Keep the cache
                     self.current_actors_info[0]['settings']['active_texture_maps'] # Use the updated active set
                 )
                 # Also update the color button visual if the override was removed from the panel
                 if not pv_color_rgb:
                      self.control_panel_widget._update_color_button_visual(None)


        except Exception as e:
            print(f"[ERROR] Color override failed: {e}")
            traceback.print_exc()
            QMessageBox.warning(self, "Color Override Error", f"Could not apply color override:\n{e}")


    # --- Texture Slots ---
    @Slot(str, bool)
    def on_texture_visibility_changed(self, tex_type, visible):
        """Applies/removes the BaseColor texture. Other maps are currently informational."""
        if not self.current_actors_info: return
        if not self.plotter: return

        print(f"-> Action: Texture Visibility Changed: '{tex_type}' = {visible}")
        applied_visual_change = False

        try:
            for info in self.current_actors_info:
                actor = info.get('actor')
                settings = info.get('settings')
                mesh = info.get('mesh')
                if not actor or not settings or not mesh: continue

                actor_name = settings.get('name', 'Unknown')

                # --- Update internal state first ---
                # Modify the 'active_texture_maps' set in the actor's settings
                if visible:
                    settings['active_texture_maps'].add(tex_type)
                    print(f"   Marked '{tex_type}' as active for {actor_name}")
                else:
                    settings['active_texture_maps'].discard(tex_type)
                    print(f"   Marked '{tex_type}' as inactive for {actor_name}")

                # --- Apply the visual change (currently only for BaseColor) ---
                if tex_type == TEX_BASE_COLOR and settings.get('is_polydata'):
                    base_tex_object = settings.get('texture_maps', {}).get(TEX_BASE_COLOR)

                    if visible and base_tex_object is not None and settings.get('uv_coords') is not None:
                        # Check if color override is active - if so, texture shouldn't be visible
                        if settings.get('color') is not None:
                             print(f"   Cannot apply {tex_type} to {actor_name}: Color override is active.")
                             # Force the checkbox to revert state if override is on
                             if hasattr(self, 'control_panel_widget') and tex_type in self.control_panel_widget._texture_widgets:
                                 cb = self.control_panel_widget._texture_widgets[tex_type]['checkbox']
                                 cb.blockSignals(True); cb.setChecked(False); cb.blockSignals(False)
                             settings['active_texture_maps'].discard(tex_type) # Correct internal state too
                        else:
                             print(f"   Applying {tex_type} texture to {actor_name}")
                             actor.texture = base_tex_object
                             actor.mapper.scalar_visibility = False # Texture overrides scalars
                             actor.color = None # Ensure solid color override is off
                             settings['color'] = None # Update settings
                             applied_visual_change = True
                    elif not visible:
                        # Remove the texture if it is currently the base color one
                        if actor.texture == base_tex_object:
                             print(f"   Removing {tex_type} texture from {actor_name}")
                             actor.texture = None
                             applied_visual_change = True
                             # --- Revert to scalars/default color ---
                             # (Similar logic to removing color override)
                             restored = False
                             if settings.get('original_scalars_info'):
                                 original_scalars = settings['original_scalars_info']
                                 if original_scalars in mesh.point_data or original_scalars in mesh.cell_data:
                                     print(f"     Restoring original scalars '{original_scalars}'")
                                     actor.mapper.scalar_visibility = True
                                     actor.mapper.SetScalarModeToUsePointFieldData() if original_scalars in mesh.point_data else actor.mapper.SetScalarModeToUseCellFieldData()
                                     actor.mapper.SelectColorArray(original_scalars)
                                     restored = True
                                 else: settings['original_scalars_info'] = None # Clear if no longer valid
                             elif mesh.active_scalars is not None:
                                 print(f"     Restoring active scalars '{mesh.active_scalars_info.name}'")
                                 actor.mapper.scalar_visibility = True
                                 actor.mapper.SetScalarModeToUsePointFieldData() if mesh.active_scalars_info.association == pv.FieldAssociation.POINT else actor.mapper.SetScalarModeToUseCellFieldData()
                                 actor.mapper.SelectColorArray(mesh.active_scalars_info.name)
                                 restored = True

                             if not restored:
                                 print("     No scalars found, setting default grey color.")
                                 actor.mapper.scalar_visibility = False
                                 actor.color = 'lightgrey' # Fallback color using PyVista property

                elif tex_type != TEX_BASE_COLOR:
                     # For other texture types (Normal, Roughness, etc.), we just track the state.
                     # Applying them visually requires shader programming or more advanced PyVista features.
                     print(f"   (Visual effect toggle for {tex_type} is not implemented, state tracked only)")

            # Render only if a visual change was actually applied
            if applied_visual_change:
                self.plotter.render()

            # Update status bar based on the internal state change
            status_msg = f"Texture '{tex_type}' marked {'active' if visible else 'inactive'}"
            if tex_type == TEX_BASE_COLOR and applied_visual_change:
                 status_msg = f"{tex_type} visual effect {'On' if visible else 'Off'}"
            self.status_bar.showMessage(status_msg, 2000)

        except Exception as e:
            print(f"[ERROR] Texture visibility change failed for '{tex_type}': {e}")
            traceback.print_exc()
            # Optionally try to revert the checkbox state on error
            if hasattr(self, 'control_panel_widget') and tex_type in self.control_panel_widget._texture_widgets:
                cb = self.control_panel_widget._texture_widgets[tex_type]['checkbox']
                cb.blockSignals(True); cb.setChecked(not visible); cb.blockSignals(False)
            # Attempt to revert internal state too
            if visible: settings['active_texture_maps'].discard(tex_type)
            else: settings['active_texture_maps'].add(tex_type)


    @Slot(str)
    def on_view_texture(self, tex_type):
        """Triggers the texture preview dialog via the control panel."""
        print(f"-> Action: View Texture '{tex_type}'")
        # Check if the control panel widget exists before accessing its methods
        if hasattr(self, 'control_panel_widget') and self.control_panel_widget is not None:
            # Use the show_texture_preview method in ControlPanel
            # The ControlPanel holds the texture cache
            pil_image = self.control_panel_widget.get_texture_from_cache(tex_type)
            if pil_image:
                 dialog = TexturePreviewDialog(tex_type, pil_image, self)
                 dialog.exec() # Show the dialog modally
                 print(f"[App] Texture preview shown for {tex_type}.")
            else:
                 QMessageBox.information(self, "Texture Preview", f"No image data available for '{tex_type}'.")
                 print(f"[App] No texture data found in cache for preview: {tex_type}.")
        else:
            print("[ERROR] Control panel not available to show texture preview.")


    # --- Skeleton/Animation Slots (Placeholders) ---
    @Slot(bool)
    def on_toggle_skeleton(self, checked):
        """Toggles the visibility of the placeholder skeleton actor."""
        if not self.current_actors_info: return
        print(f"-> Action: Toggle Skeleton ({checked}) (Placeholder)")
        found_skeleton = False
        if self.plotter:
            try:
                for info in self.current_actors_info:
                    skeleton_actor = info.get('settings', {}).get('skeleton_actor')
                    if skeleton_actor:
                        skeleton_actor.SetVisibility(checked)
                        found_skeleton = True
                if found_skeleton:
                    self.plotter.render()
                    self.status_bar.showMessage(f"Skeleton visibility {'On' if checked else 'Off'}", 2000)
                else:
                    self.status_bar.showMessage("No skeleton data found for this model.", 3000)
                    # Ensure the checkbox reflects reality
                    if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'skeleton_checkbox'):
                        cb = self.control_panel_widget.skeleton_checkbox
                        cb.blockSignals(True); cb.setChecked(False); cb.blockSignals(False)
            except Exception as e:
                 print(f"[ERROR] Failed to toggle skeleton visibility: {e}")
                 self.status_bar.showMessage("Error toggling skeleton.", 3000)
        else:
             self.status_bar.showMessage("Plotter not available.", 3000)


    @Slot(str)
    def on_play_animation(self, animation_name):
        """Placeholder slot for playing an animation."""
        print(f"-> Action: Play Animation '{animation_name}' (Not Implemented)")
        # --- Animation Playback Implementation Required ---
        # 1. Get the animation data (e.g., from self.scene_graph using Trimesh or another library)
        #    - Find the animation by name.
        #    - Extract keyframes (times, transforms) for affected nodes.
        # 2. Create a timer (e.g., QTimer).
        # 3. In the timer's slot:
        #    - Calculate the current time within the animation loop.
        #    - Interpolate transforms for affected nodes based on keyframes.
        #    - Update the corresponding actors/nodes in the PyVista scene.
        #      (This might involve manipulating VTK matrices directly if using a Trimesh scene graph representation,
        #       or updating actor positions/orientations if using simple actors).
        #    - Request a render for the plotter (self.plotter.render()).
        # 4. Handle starting, stopping, looping, speed control.
        # -----------------------------------------------
        QMessageBox.information(self, "Animation", f"Playback for '{animation_name}' is not yet implemented.")
        self.status_bar.showMessage("Animation playback is not implemented.", 3000)

    @Slot()
    def on_stop_animation(self):
        """Placeholder slot for stopping animation."""
        print("-> Action: Stop Animation (Not Implemented)")
        # --- Animation Stop Implementation Required ---
        # - Stop the QTimer created in on_play_animation.
        # - Optionally reset the node transforms to a base pose.
        # ------------------------------------------
        self.status_bar.showMessage("Animation stopped (Not Implemented).", 2000)

    # --- Help Slot ---
    @Slot()
    def on_about(self):
        """Displays the About dialog."""
        print("-> Action: About")
        about_text = f"""
        <h2>{APP_NAME} v{APP_VERSION}</h2>
        <hr>
        <p>An advanced 3D model viewer application.</p>
        <p>Built using:</p>
        <ul>
            <li>Python</li>
            <li>PySide6 (Qt for Python)</li>
            <li>PyVista & VTK (Visualization)</li>
            <li>pyvistaqt (Qt Integration)</li>
            <li>Trimesh (Model Loading & Processing)</li>
            <li>Pillow (Texture Handling)</li>
            <li>imageio (HDR Loading)</li>
            <li>pyassimp (Optional for FBX)</li>
        </ul>
        <p>Features include model loading (GLB, GLTF, OBJ, STL, PLY, FBX, etc.),
        texture support, HDR environments, lighting presets,
        and interactive controls.</p>
        <br>
        <p><small><i>Note: Animation playback and full PBR material support
        are currently placeholders or limited. FBX support requires the optional pyassimp library and its native Assimp library.</i></small></p>
        """
        QMessageBox.about(self, f"About {APP_NAME}", about_text)


    # --- Core Loading Logic ---

    def _load_model_file(self, file_path):
        """Loads a 3D model file using Trimesh (preferred) or PyVista."""
        print(f"\n--- Loading Model: {os.path.basename(file_path)} ---")
        self.status_bar.showMessage(f"Loading {os.path.basename(file_path)}...")
        QApplication.processEvents() # Keep UI responsive during load attempt

        # --- Reset State ---
        # Close any previously loaded model first
        if self.current_actors_info:
            self.on_close_model()
            QApplication.processEvents() # Ensure UI updates after close

        # Initialize variables for this load attempt
        mesh_pv = None # The PyVista mesh object to be added
        actor_settings = self.DEFAULT_ACTOR_SETTINGS.copy() # Start with a new default settings dict
        loaded_success = False
        load_method = "Unknown"
        texture_status = "N/A"
        loaded_pil_textures = {} # {tex_type: PIL.Image}
        animations_found = [] # List of animation names
        scene_graph_data = None # Store the Trimesh scene if available
        file_extension = os.path.splitext(file_path)[1].lower()

        try:
            # --- Attempt 1: Trimesh (for GLTF/GLB, OBJ with textures, FBX etc.) ---
            # Check if Trimesh is available and if the file extension is supported by Trimesh
            # For FBX, also check if pyassimp is available
            is_fbx = file_extension == '.fbx'
            can_load_with_trimesh = TRIMESH_AVAILABLE and (
                file_extension in ['.glb', '.gltf', '.obj', '.stl', '.ply', '.vtk', '.vtp', '.vts', '.dae'] or
                (is_fbx and PYASSIMP_AVAILABLE) # Only attempt FBX with Trimesh if pyassimp is present
            )

            if can_load_with_trimesh:
                print("[LOAD] Attempting load with Trimesh...")
                if is_fbx and not PYASSIMP_AVAILABLE:
                    # This case should be caught by can_load_with_trimesh, but double check and warn
                    print("[WARN] Cannot load FBX with Trimesh: pyassimp library is missing.")
                    # Skip Trimesh attempt for FBX if pyassimp is missing
                else:
                    try:
                        # Load the file. process=False prevents initial mesh merging.
                        # enable_post_processing=True can help fix issues but might be slow.
                        # Consider force='scene' for GLTF/GLTF/DAE/FBX to ensure scene graph access.
                        kwargs = {'process': False, 'enable_post_processing': True}
                        if file_extension in ['.glb', '.gltf', '.dae', '.fbx']: # These formats often benefit from scene loading
                            kwargs['force'] = 'scene' # Try to get scene graph

                        scene_or_mesh = trimesh.load(file_path, **kwargs)
                        print(f"  [Trimesh] Loaded data type: {type(scene_or_mesh)}")

                        tm_mesh_combined = None # The combined Trimesh geometry
                        uv_coords = None

                        if isinstance(scene_or_mesh, trimesh.Scene):
                            print("  [Trimesh] Scene loaded.")
                            scene_graph_data = scene_or_mesh # Store the scene graph
                            # Extract animation names if present
                            if hasattr(scene_or_mesh, 'animations') and scene_or_mesh.animations:
                                animations_found = [a.name for a in scene_or_mesh.animations if hasattr(a, 'name')]
                                print(f"    Found {len(animations_found)} animations: {animations_found}")

                            # Concatenate all geometry in the scene into a single mesh for simple display
                            # Note: This loses individual node transforms for simple rendering
                            if scene_or_mesh.geometry:
                                 # Use scene.to_geometry() instead of deprecated dump(concatenate=True)
                                 tm_mesh_combined = scene_or_mesh.to_geometry()
                                 if tm_mesh_combined is not None and not tm_mesh_combined.is_empty:
                                      print(f"  [Trimesh] Scene geometry concatenated into single mesh (Vertices: {tm_mesh_combined.vertices.shape[0]}, Faces: {tm_mesh_combined.faces.shape[0]})")
                                      # Attempt to get textures/UVs from the *first* geometry in the scene
                                      # This is an approximation, as different parts might have different materials.
                                      # A more robust approach would iterate through all geometries.
                                      first_geom_name = next(iter(scene_or_mesh.geometry.keys()), None)
                                      if first_geom_name:
                                           first_geom = scene_or_mesh.geometry[first_geom_name]
                                           print(f"    Extracting textures/UVs from first geometry: '{first_geom_name}' ({type(first_geom)})")
                                           loaded_pil_textures = self._extract_all_trimesh_textures(first_geom)
                                           uv_coords = self._extract_trimesh_uvs(first_geom)
                                           # If UVs are missing in the first geometry, check the visual of the combined mesh
                                           if uv_coords is None and hasattr(tm_mesh_combined, 'visual') and hasattr(tm_mesh_combined.visual, 'uv') and tm_mesh_combined.visual.uv is not None:
                                               uv_coords = tm_mesh_combined.visual.uv
                                               if uv_coords is not None: print("    Used UVs from combined mesh visual.")
                                      else:
                                           print("[WARN] Trimesh scene contained no displayable geometry after concatenation.")
                                           tm_mesh_combined = None
                            else:
                                 print("[WARN] Trimesh scene has no geometry.")


                        elif isinstance(scene_or_mesh, trimesh.Trimesh):
                            # A single mesh was loaded directly
                            print("  [Trimesh] Single mesh loaded.")
                            if not scene_or_mesh.is_empty:
                                tm_mesh_combined = scene_or_mesh
                                loaded_pil_textures = self._extract_all_trimesh_textures(tm_mesh_combined)
                                uv_coords = self._extract_trimesh_uvs(tm_mesh_combined)
                            else:
                                print("[WARN] Trimesh mesh is empty.")
                                tm_mesh_combined = None

                        # --- Convert Trimesh result to PyVista ---
                        if tm_mesh_combined is not None and tm_mesh_combined.faces is not None and len(tm_mesh_combined.faces) > 0:
                            print("[LOAD] Converting Trimesh mesh to PyVista PolyData...")
                            # Use pv.wrap for efficient conversion
                            mesh_pv = pv.wrap(tm_mesh_combined)
                            if not isinstance(mesh_pv, pv.PolyData):
                                 print(f"[WARN] Wrapped Trimesh mesh is not PolyData ({type(mesh_pv)}), texture/UV assignment might fail.")
                            actor_settings['is_polydata'] = isinstance(mesh_pv, pv.PolyData)

                            # Assign UV coordinates if valid
                            if actor_settings['is_polydata'] and uv_coords is not None:
                                # PyVista expects texture coordinates in point data
                                # Check if the number of UVs matches the number of points
                                if uv_coords.shape[0] == mesh_pv.n_points and uv_coords.shape[1] == 2:
                                    # Ensure UVs are float32 as expected by VTK/PyVista
                                    mesh_pv.texture_coordinates = pv.pyvista_ndarray(uv_coords.astype(np.float32))
                                    actor_settings['uv_coords'] = mesh_pv.texture_coordinates # Store the assigned coords
                                    print(f"  [LOAD] Assigned UV coordinates ({uv_coords.shape}) to PyVista mesh.")
                                else:
                                    print(f"[WARN] UV coordinate dimensions ({uv_coords.shape}) do not match mesh points ({mesh_pv.n_points}). Skipping UV assignment.")
                                    actor_settings['uv_coords'] = None
                            elif actor_settings['is_polydata']:
                                 print("  [LOAD] No valid UV coordinates found or extracted.")
                                 actor_settings['uv_coords'] = None


                            # Convert loaded PIL textures to PyVista textures
                            if actor_settings['is_polydata'] and actor_settings['uv_coords'] is not None and loaded_pil_textures and PILLOW_AVAILABLE:
                                print(f"  [LOAD] Converting {len(loaded_pil_textures)} PIL textures to PyVista textures...")
                                for tex_type, pil_img in loaded_pil_textures.items():
                                    pv_tex = self._convert_pillow_to_pvtexture(pil_img)
                                    if pv_tex:
                                        actor_settings['texture_maps'][tex_type] = pv_tex
                                        print(f"    Converted '{tex_type}'")
                                if actor_settings['texture_maps']:
                                     actor_settings['has_texture'] = True
                                     # Determine texture status based on what was loaded
                                     if TEX_BASE_COLOR in actor_settings['texture_maps']: texture_status = "BaseColor (Trimesh)"
                                     else: texture_status = f"{len(actor_settings['texture_maps'])} Maps (Trimesh)"
                            elif actor_settings['is_polydata'] and actor_settings['uv_coords'] is None:
                                 texture_status = "UVs Missing (Trimesh)"
                            elif not loaded_pil_textures:
                                 texture_status = "None Found (Trimesh)"


                            # Check for vertex colors from Trimesh
                            if hasattr(tm_mesh_combined.visual, 'vertex_colors') and tm_mesh_combined.visual.vertex_colors is not None:
                                 vc = tm_mesh_combined.visual.vertex_colors
                                 if len(vc) == mesh_pv.n_points:
                                      print(f"  [LOAD] Found vertex colors ({vc.shape}) from Trimesh.")
                                      # Ensure RGBA, uint8 format for PyVista scalars
                                      if vc.shape[1] == 3: # Add alpha channel if missing
                                           vc = np.hstack((vc, np.full((vc.shape[0], 1), 255, dtype=vc.dtype)))
                                      if vc.dtype != np.uint8:
                                           # Normalize if float (assuming 0-1 range), then scale to 0-255
                                           if np.issubdtype(vc.dtype, np.floating):
                                                vc = (np.clip(vc, 0.0, 1.0) * 255).astype(np.uint8)
                                           else: # Assume integer type, just ensure uint8
                                                vc = vc.astype(np.uint8)
                                      # Add as point data with a specific name (e.g., 'RGBA')
                                      mesh_pv.point_data['RGBA'] = vc
                                      actor_settings['has_vertex_colors'] = True
                                      if not actor_settings['has_texture']: # If no texture, vertex colors are primary
                                           texture_status = "Vertex Colors (Trimesh)"
                                 else:
                                      print(f"[WARN] Vertex color count ({len(vc)}) differs from mesh points ({mesh_pv.n_points}). Skipping.")

                            loaded_success = True
                            load_method = "Trimesh"
                        else:
                            print("[LOAD] Trimesh loaded data, but no valid/convertible geometry found.")

                    except Exception as e_tm:
                        print(f"[WARN] Trimesh load failed: {type(e_tm).__name__}: {e_tm}")
                        # Don't raise exception here, allow PyVista fallback
                        traceback.print_exc(limit=1) # Print limited traceback for debugging


            # --- Attempt 2: PyVista Fallback (for VTK formats, STL, PLY, maybe others) ---
            if not loaded_success:
                print("[LOAD] Attempting fallback load with PyVista reader...")
                try:
                    # pv.read is a general-purpose reader
                    pv_obj = pv.read(file_path)
                    print(f"  [PyVista] Loaded object type: {type(pv_obj)}")

                    # Handle different PyVista object types
                    if isinstance(pv_obj, pv.MultiBlock):
                        print("  [PyVista] MultiBlock dataset loaded, combining blocks...")
                        # Combine into a single PolyData if possible
                        mesh_pv = pv_obj.combine(merge_points=True) # merge_points can be slow
                        load_method = "PyVista (MultiBlock)"
                    elif isinstance(pv_obj, pv.DataSet): # Includes PolyData, UnstructuredGrid, etc.
                        mesh_pv = pv_obj
                        load_method = f"PyVista ({type(pv_obj).__name__})"
                    else:
                        # This shouldn't happen if pv.read succeeded, but handle it anyway
                        raise TypeError(f"PyVista reader returned unsupported type: {type(pv_obj)}")

                    # Basic sanity check
                    if mesh_pv is None or mesh_pv.n_points == 0:
                        raise ValueError("Mesh loaded by PyVista is empty or invalid.")

                    print(f"  [PyVista] Mesh details - Points: {mesh_pv.n_points}, Cells: {mesh_pv.n_cells}")
                    actor_settings['is_polydata'] = isinstance(mesh_pv, pv.PolyData)

                    # Check for textures and UVs (more likely for PolyData)
                    if actor_settings['is_polydata']:
                        if hasattr(mesh_pv, 'textures') and mesh_pv.textures:
                            # PyVista found internal textures (e.g., from some VTK formats)
                            texture_status = f"Internal ({len(mesh_pv.textures)}) (PyVista)"
                            actor_settings['has_texture'] = True
                            # Store these textures? Might need different handling.
                            # actor_settings['texture_maps']['pyvista_internal'] = mesh_pv.textures
                        if mesh_pv.texture_coordinates is not None:
                             print("  [PyVista] Found texture coordinates.")
                             actor_settings['uv_coords'] = mesh_pv.texture_coordinates
                             if not actor_settings['has_texture']: texture_status = "UVs Only (PyVista)"
                        elif not actor_settings['has_texture']:
                             texture_status = "None (PyVista)"

                    # Check for active scalars (vertex colors)
                    if mesh_pv.active_scalars is not None:
                        print(f"  [PyVista] Found active scalars: '{mesh_pv.active_scalars_info.name}', Min: {mesh_pv.active_scalars.min()}, Max: {mesh_pv.active_scalars.max()}")
                        actor_settings['has_vertex_colors'] = True
                        if not actor_settings['has_texture']: # Primary only if no texture
                             texture_status = f"Scalars '{mesh_pv.active_scalars_info.name}' (PyVista)"
                    elif not actor_settings['has_texture'] and not actor_settings['uv_coords']:
                         texture_status = "None (PyVista)"


                    loaded_success = True

                except Exception as e_pv:
                    print(f"[ERROR] PyVista load failed: {type(e_pv).__name__}: {e_pv}")
                    # If Trimesh also failed (e_tm exists), re-raise the Trimesh error as it might be more informative
                    # Otherwise, re-raise the PyVista error.
                    # raise e_tm if 'e_tm' in locals() else e_pv
                    # More simply, just report that PyVista failed and let the final check handle it.
                    pass # Allow the final check below


            # --- Step 3: Final Check and Add Actor to Plotter ---
            if not loaded_success or mesh_pv is None:
                # If neither method succeeded, raise an error
                raise RuntimeError("Failed to load model using both Trimesh and PyVista.")

            print(f"\n[LOAD] Successfully loaded mesh using: {load_method}")
            print(f"[LOAD] Texture Status: {texture_status}")
            print(f"[LOAD] Animations Found: {len(animations_found)}")

            self.current_file_path = file_path
            self.animations = animations_found # Store found animation names
            self.scene_graph = scene_graph_data # Store the Trimesh scene if available

            # --- Set up actor settings and add_mesh kwargs ---
            actor_settings['name'] = f"actor_{os.path.basename(file_path)}"

            # Store original scalars info before potential override
            if mesh_pv.active_scalars is not None:
                 actor_settings['original_scalars_info'] = mesh_pv.active_scalars_info.name
            else: actor_settings['original_scalars_info'] = None


            # Get initial display properties from control panel defaults
            # Must check if control_panel_widget exists before accessing its attributes
            if hasattr(self, 'control_panel_widget'):
                panel = self.control_panel_widget
                initial_opacity = panel.opacity_slider.value() / 100.0
                initial_show_edges = panel.edges_checkbox.isChecked()
                initial_style = panel.rep_style_group.checkedButton().text().lower()
                initial_point_size = panel.point_size_spinbox.value()
            else:
                # Fallback defaults if control panel is not available
                print("[WARN] Control panel not available, using default actor properties.")
                initial_opacity = self.DEFAULT_ACTOR_SETTINGS['opacity']
                initial_show_edges = self.DEFAULT_ACTOR_SETTINGS['show_edges']
                initial_style = self.DEFAULT_ACTOR_SETTINGS['representation']
                initial_point_size = self.DEFAULT_ACTOR_SETTINGS['point_size']


            add_mesh_kwargs = {
                "mesh": mesh_pv,
                "name": actor_settings['name'],
                "smooth_shading": True, # Generally looks better
                "opacity": initial_opacity,
                "show_edges": initial_show_edges,
                "style": initial_style,
                "point_size": initial_point_size
                # "color" and "texture" are determined below
            }

            # Update the actor_settings dict with these initial visual properties
            actor_settings.update({
                'opacity': add_mesh_kwargs['opacity'],
                'show_edges': add_mesh_kwargs['show_edges'],
                'point_size': add_mesh_kwargs['point_size'],
                'representation': add_mesh_kwargs['style'] # Use 'representation' in settings
            })

            # --- Determine Coloring/Texturing for add_mesh ---
            base_color_tex = actor_settings['texture_maps'].get(TEX_BASE_COLOR)

            if actor_settings['is_polydata'] and base_color_tex is not None and actor_settings['uv_coords'] is not None:
                # Priority 1: BaseColor texture with UV coordinates
                print("  [AddMesh] Applying BaseColor texture.")
                add_mesh_kwargs["texture"] = base_color_tex
                add_mesh_kwargs["scalars"] = None # Don't use scalars if texture is applied
                add_mesh_kwargs["rgb"] = False
                # Mark BaseColor as active initially
                actor_settings['active_texture_maps'].add(TEX_BASE_COLOR)

            elif actor_settings['has_vertex_colors']:
                # Priority 2: Vertex colors (scalars)
                scalars_name_to_use = None
                if 'RGBA' in mesh_pv.point_data: # Prefer explicit RGBA if found (e.g., from Trimesh)
                    scalars_name_to_use = 'RGBA'
                elif actor_settings['original_scalars_info']: # Use original active scalars if present
                    scalars_name_to_use = actor_settings['original_scalars_info']
                elif mesh_pv.active_scalars is not None: # Fallback to current active scalars
                     scalars_name_to_use = mesh_pv.active_scalars_info.name


                if scalars_name_to_use:
                     print(f"  [AddMesh] Using Vertex Colors/Scalars: '{scalars_name_to_use}'")
                     add_mesh_kwargs["scalars"] = scalars_name_to_use
                     add_mesh_kwargs["rgb"] = True # Interpret scalars as RGB(A) colors
                     # Ensure scalar mode is set correctly (PointData or CellData)
                     if scalars_name_to_use in mesh_pv.point_data:
                         add_mesh_kwargs["scalar_mode"] = 'point'
                     elif scalars_name_to_use in mesh_pv.cell_data:
                         add_mesh_kwargs["scalar_mode"] = 'cell'
                     else:
                         add_mesh_kwargs["scalar_mode"] = 'default' # Let PyVista decide
                         print(f"[WARN] Scalar array '{scalars_name_to_use}' not found in point or cell data. Scalar mode might be incorrect.")

                else:
                     # This shouldn't happen if has_vertex_colors is True, but as a fallback:
                     print("  [AddMesh] Vertex colors expected but no suitable scalars found. Using default color.")
                     add_mesh_kwargs["color"] = 'lightgrey' # Use a default color
                     add_mesh_kwargs["scalars"] = None
                     add_mesh_kwargs["rgb"] = False
                     actor_settings['has_vertex_colors'] = False # Correct the flag


            else:
                # Priority 3: No texture, no vertex colors - use a default solid color
                print("  [AddMesh] No textures or vertex colors found. Using default solid color.")
                add_mesh_kwargs["color"] = 'gainsboro' # Default color for models without color info
                add_mesh_kwargs["scalars"] = None
                add_mesh_kwargs["rgb"] = False


            # --- Add the mesh to the plotter ---
            if not self.plotter: raise RuntimeError("Plotter object not available.")

            # Print add_mesh kwargs (avoid printing the mesh object itself)
            print(f"  [AddMesh] Calling plotter.add_mesh with args: { {k: v if k!='mesh' else type(v) for k,v in add_mesh_kwargs.items()} }")
            actor = self.plotter.add_mesh(**add_mesh_kwargs)

            if actor is None:
                 raise RuntimeError("plotter.add_mesh did not return a valid actor.")

            # Store the actor, settings, and mesh reference
            self.current_actors_info.append({
                'actor': actor,
                'settings': actor_settings,
                'mesh': mesh_pv # Store a reference to the mesh data
            })
            print(f"  [LOAD] Actor '{actor_settings['name']}' added to the scene.")

            # --- Placeholder for Skeleton ---
            # Currently disabled - requires extracting actual skeleton and visualization logic
            skeleton_actor = self._create_skeleton_actor(scene_graph_data) # Pass the scene if available
            actor_settings['skeleton_actor'] = skeleton_actor
            if skeleton_actor:
                 print("  [LOAD] Placeholder skeleton actor created (visibility off).")


            # --- Final UI Updates ---
            self.plotter.reset_camera() # Fit camera to the newly loaded model
            self.update_ui_state(model_loaded=True) # Enable relevant UI controls

            # Update the control panel to reflect the loaded model's state
            if hasattr(self, 'control_panel_widget'):
                # Update model display controls based on the actor's initial state
                self.control_panel_widget.update_controls_from_state(actor_settings)
                # Update the texture list in the control panel
                self.control_panel_widget.update_texture_slots(loaded_pil_textures, actor_settings['active_texture_maps'])
                # Update the animation list
                self.control_panel_widget.update_animation_list(self.animations)
                # Enable/disable skeleton/animation controls based on loaded data
                self.control_panel_widget.set_skel_anim_controls_enabled(
                     has_skeleton=(skeleton_actor is not None),
                     has_animations=bool(self.animations)
                )


            # Update window title and status bar
            self.setWindowTitle(f"{APP_NAME} - {os.path.basename(file_path)}")
            self.status_bar.showMessage(f"Loaded: {os.path.basename(file_path)} ({load_method}) | Textures: {texture_status}", 10000)
            print(f"--- Load Complete: {os.path.basename(file_path)} ---")

        except FileNotFoundError:
            self._handle_load_error(f"File not found: {file_path}", file_path)
        except Exception as e:
            # Catch any other exceptions during the loading process
            self._handle_load_error(e, file_path)


    # --- Helper Functions ---

    def _handle_load_error(self, error, file_path, is_hdr=False):
        """Handles errors during model or HDR loading."""
        error_type = type(error).__name__
        error_message = str(error)
        error_prefix = "HDR Load Error" if is_hdr else "Model Load Error"
        full_error_message = f"{error_prefix} for '{os.path.basename(file_path)}':\n\n{error_type}: {error_message}"

        print(f"[ERROR] {full_error_message}")
        # Print traceback for non-FileNotFoundError errors for debugging
        if not isinstance(error, FileNotFoundError):
            print("\n--- Traceback ---")
            traceback.print_exc()
            print("-----------------\n")

        # Add specific notes for problematic formats
        file_extension = os.path.splitext(file_path)[1].lower() if file_path else ''
        notes = ""
        if not is_hdr:
            if file_extension == ".fbx":
                notes = "\n\n(Note: FBX support is often limited and requires the 'pyassimp' library and its native Assimp library. Please ensure both are correctly installed.)"
            elif file_extension in [".glb", ".gltf"]:
                notes = "\n\n(Note: Ensure GLTF/GLTF file is valid. Complex features might not be fully supported.)"
            elif file_extension == ".obj":
                 notes = "\n\n(Note: For OBJ textures, ensure MTL file and texture images are in the same directory or paths are correct.)"

        # Display the error message box to the user
        QMessageBox.critical(self, f"{error_prefix}", full_error_message + notes + "\n\nSee console output for more details.")

        # Update UI state
        self.status_bar.showMessage(f"{error_prefix} failed.", 5000)
        if not is_hdr:
             # If model load failed, ensure the scene is cleared and UI is reset
             self.on_close_model() # This calls update_ui_state(model_loaded=False)
             self.setWindowTitle(APP_NAME)
        else:
             # If HDR load failed, ensure HDR state is cleared
             self.loaded_hdr_texture = None
             if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'clear_hdr_button'):
                 self.control_panel_widget.clear_hdr_button.setEnabled(False)
             self.action_clear_hdr.setEnabled(False)
             # Optionally revert lighting if it was set to Environment
             if hasattr(self, 'control_panel_widget') and hasattr(self.control_panel_widget, 'lighting_combo'):
                 combo = self.control_panel_widget.lighting_combo
                 if "Environment" in combo.currentText():
                      combo.blockSignals(True); combo.setCurrentText("Default Kit"); combo.blockSignals(False)
                      self._apply_light_preset("Default Kit")


    def _extract_all_trimesh_textures(self, tm_mesh):
        """Extracts all known PBR texture types from a Trimesh material."""
        textures_pil = {} # {tex_type: PIL.Image}
        if not isinstance(tm_mesh, trimesh.Trimesh) or not hasattr(tm_mesh, 'visual'):
            # print("    [TexExtract] Mesh has no visual component.")
            return textures_pil
        if not PILLOW_AVAILABLE:
             print("    [TexExtract] Pillow library not available, cannot extract textures.")
             return textures_pil

        material = getattr(tm_mesh.visual, 'material', None)
        if not material:
             # Sometimes texture info is directly on the visual if PBRMaterial isn't used
             if isinstance(tm_mesh.visual, trimesh.visual.texture.TextureVisuals):
                  if hasattr(tm_mesh.visual, 'material') and tm_mesh.visual.material:
                       material = tm_mesh.visual.material
                  elif hasattr(tm_mesh.visual, 'image') and isinstance(tm_mesh.visual.image, Image.Image):
                       # Found an image directly on TextureVisuals, assign it as BaseColor
                       print("    [TexExtract] Found image directly on TextureVisuals, assigning as BaseColor.")
                       textures_pil[TEX_BASE_COLOR] = tm_mesh.visual.image
                       return textures_pil
                  else:
                       # print("    [TexExtract] No material found on visual component.")
                       return textures_pil
             else:
                  # print("    [TexExtract] No material found on visual component.")
                  return textures_pil


        print(f"    [TexExtract] Extracting textures from material: {type(material).__name__}")

        # Map our texture type keys to Trimesh material attributes
        # Prioritize specific PBR slots, then fall back to generic 'image'
        texture_attribute_map = {
            TEX_BASE_COLOR: 'baseColorTexture',
            TEX_METALLIC_ROUGHNESS: 'metallicRoughnessTexture',
            TEX_NORMAL: 'normalTexture',
            TEX_OCCLUSION: 'occlusionTexture',
            TEX_EMISSIVE: 'emissiveTexture',
            TEX_GENERIC_IMAGE: 'image' # Fallback if others aren't present
        }

        for tex_type, attr_name in texture_attribute_map.items():
            texture_object = getattr(material, attr_name, None)
            # Check if the attribute exists and has an 'image' attribute that is a PIL Image
            if hasattr(texture_object, 'image') and isinstance(texture_object.image, Image.Image):
                 # Check if this specific type has already been assigned
                 if tex_type not in textures_pil:
                      textures_pil[tex_type] = texture_object.image
                      print(f"      Found PIL Image for: {tex_type} (from attr: {attr_name})")
            elif isinstance(texture_object, Image.Image):
                 # Handle cases where the image is directly the attribute value (less common for PBR slots)
                 if tex_type not in textures_pil:
                      textures_pil[tex_type] = texture_object
                      print(f"      Found PIL Image for: {tex_type} (direct from attr: {attr_name})")


        # Handle the generic 'image' case: if BaseColor wasn't found specifically,
        # use the generic 'image' as BaseColor if it exists.
        if TEX_BASE_COLOR not in textures_pil and TEX_GENERIC_IMAGE in textures_pil:
            print(f"      Using generic '{TEX_GENERIC_IMAGE}' as {TEX_BASE_COLOR}.")
            textures_pil[TEX_BASE_COLOR] = textures_pil[TEX_GENERIC_IMAGE]
            # Remove the generic entry if it's now duplicated
            del textures_pil[TEX_GENERIC_IMAGE]
        elif TEX_GENERIC_IMAGE in textures_pil and TEX_BASE_COLOR in textures_pil and textures_pil[TEX_GENERIC_IMAGE] == textures_pil[TEX_BASE_COLOR]:
             # Clean up the generic entry if it's identical to the specific BaseColor
             del textures_pil[TEX_GENERIC_IMAGE]


        if not textures_pil:
             print("    [TexExtract] No PIL texture images found in material attributes.")

        return textures_pil


    def _extract_trimesh_uvs(self, tm_mesh):
        """Extracts UV coordinates from a Trimesh object."""
        if isinstance(tm_mesh, trimesh.Trimesh) and \
           hasattr(tm_mesh, 'visual') and \
           hasattr(tm_mesh.visual, 'uv') and \
           tm_mesh.visual.uv is not None:
            uvs = tm_mesh.visual.uv
            print(f"    [UVExtract] Found UV coordinates: Shape={uvs.shape}, Type={uvs.dtype}")
            # Basic sanity check
            if len(uvs.shape) == 2 and uvs.shape[1] == 2:
                return uvs
            else:
                print(f"[WARN] Invalid UV shape found: {uvs.shape}. Expected (n_points, 2).")
                return None
        # print("    [UVExtract] No UV coordinates found in Trimesh visual.")
        return None


    def _convert_pillow_to_pvtexture(self, pil_image):
        """Converts a PIL Image object to a PyVista Texture object."""
        if not PILLOW_AVAILABLE or not isinstance(pil_image, Image.Image):
            print("[WARN] Cannot convert texture, Pillow unavailable or invalid image.")
            return None
        try:
            # Ensure the image is in a format PyVista understands (RGB or RGBA)
            # Convert to RGB first, as some modes might not convert directly to RGBA
            if pil_image.mode not in ['RGB', 'RGBA']:
                print(f"    Converting PIL image from mode '{pil_image.mode}' to 'RGB'.")
                img_converted = pil_image.convert('RGB')
            else:
                img_converted = pil_image

            # Create a PyVista texture from the NumPy array representation
            pv_texture = pv.Texture(np.array(img_converted))
            # print(f"    Successfully converted PIL Image (Mode: {pil_image.mode}, Size: {pil_image.size}) to PyVista Texture.")
            return pv_texture
        except Exception as e:
            print(f"[ERROR] Failed to convert PIL Image to PyVista Texture: {e}")
            traceback.print_exc()
            return None


    def _create_skeleton_actor(self, trimesh_scene=None):
        """Placeholder for creating a visual representation of a skeleton."""
        # --- Skeleton Visualization Implementation Required ---
        # This would involve:
        # 1. Accessing skeleton data (bones, joints, hierarchy) from the loaded model.
        #    - The Trimesh scene graph (scene_graph_data) might contain node transforms.
        #    - Libraries like pygltflib might be needed to parse glTF Skinning/Joint data.
        # 2. Creating PyVista geometry (e.g., lines for bones, spheres for joints)
        #    based on the skeleton structure and joint positions.
        # 3. Returning a PyVista actor (or MultiBlock) representing the skeleton.
        # 4. Linking animation updates to move the skeleton actor.
        # ----------------------------------------------------
        print("  [Skeleton] Skeleton visualization is not implemented.")
        # Example: return a dummy actor if you wanted to test the toggle
        # if self.plotter and trimesh_scene and hasattr(trimesh_scene, 'skeleton') and trimesh_scene.skeleton:
        #     try:
        #         print("  [Skeleton] Found Trimesh skeleton data (placeholder visualization)...")
        #         # Simple placeholder: just show the joint locations as spheres
        #         joint_positions = trimesh_scene.skeleton.joints # Assuming this attribute exists and is positions
        #         if joint_positions is not None and len(joint_positions) > 0:
        #             joint_points = pv.PolyData(joint_positions)
        #             skel_actor = self.plotter.add_mesh(joint_points, render_points_as_spheres=True, point_size=10, color='yellow', name='skeleton_joints_placeholder')
        #             skel_actor.SetVisibility(False) # Hidden by default
        #             return skel_actor
        #         else:
        #             print("  [Skeleton] Trimesh skeleton found but no joint positions.")
        #             return None
        #     except Exception as e:
        #         print(f"[ERROR] Could not create placeholder skeleton actor: {e}")
        #         traceback.print_exc()
        #         return None
        return None # Return None to indicate no skeleton actor was created


    def update_ui_state(self, model_loaded):
        """Enables/disables UI elements based on whether a model is loaded."""
        print(f"[UI Update] Setting UI state for model loaded: {model_loaded}")

        # Actions
        self.action_close_model.setEnabled(model_loaded)
        # HDR actions depend on library and loaded state, not just model loaded
        self.action_load_hdr.setEnabled(IMAGEIO_AVAILABLE)
        # Clear HDR is enabled only if HDR is loaded regardless of model.
        self.action_clear_hdr.setEnabled(self.loaded_hdr_texture is not None)


        # Control Panel sections
        if hasattr(self, 'control_panel_widget') and self.control_panel_widget is not None:
            self.control_panel_widget.set_model_controls_enabled(model_loaded)
            # Texture and Animation panels are enabled/disabled based on actual loaded data,
            # which happens *after* load or during model close.
            # So, explicitly disable them only on close.
            if not model_loaded:
                self.control_panel_widget.set_texture_controls_enabled(False)
                self.control_panel_widget.set_skel_anim_controls_enabled(False, False)
                # Reset the state of the clear HDR button in the panel too
                if hasattr(self.control_panel_widget, 'clear_hdr_button'):
                     # Sync panel button state with action state
                     self.control_panel_widget.clear_hdr_button.setEnabled(self.action_clear_hdr.isEnabled())
        else:
             print("[WARN] Control panel widget not found during UI state update.")

    # --- Settings Management ---
    def _load_window_settings(self):
        """Loads window state and settings from QSettings."""
        print("[Settings] Loading window settings...")
        try:
            geometry = self._settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
                print("  [Settings] Restored window geometry.")
            state = self._settings.value("windowState")
            if state:
                self.restoreState(state)
                print("  [Settings] Restored window state.")
            # Load last directory for file dialogs
            self._last_dir = self._settings.value("lastDirectory", os.path.expanduser("~"))
            print(f"  [Settings] Loaded last directory: {self._last_dir}")

            # Load control panel state if needed (more complex, requires serializing panel state)
            # For now, panel state resets with model load/close.

        except Exception as e:
            print(f"[ERROR] Failed to load window settings: {e}")
            traceback.print_exc()

    def _save_window_settings(self):
        """Saves window state and settings to QSettings."""
        print("[Settings] Saving window settings...")
        try:
            self._settings.setValue("geometry", self.saveGeometry())
            self._settings.setValue("windowState", self.saveState())
            # Save last directory
            if self.current_file_path:
                 self._settings.setValue("lastDirectory", os.path.dirname(self.current_file_path))
            elif self._last_dir:
                 self._settings.setValue("lastDirectory", self._last_dir)
            print("  [Settings] Settings saved.")

            # Save control panel state if needed

        except Exception as e:
            print(f"[ERROR] Failed to save window settings: {e}")
            traceback.print_exc()


    def closeEvent(self, event):
        """Handles the main window close event."""
        print("-> Window Close Event triggered")
        # Ask for confirmation
        reply = QMessageBox.question(self, "Confirm Exit",
                                     "Are you sure you want to exit?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No) # Default is No

        if reply == QMessageBox.StandardButton.Yes:
            print("   User confirmed exit.")
            # Perform cleanup
            self._save_window_settings() # Save settings before closing
            if self.plotter:
                try:
                    print("   Closing PyVista plotter...")
                    # It's generally safer to explicitly close the plotter's interactor
                    # This might be handled by Qt's cleanup, but being explicit is better.
                    # self.plotter.close() # This might close the entire app prematurely sometimes
                    # Instead, ensure actors are removed and let Qt handle the window close.
                    self.on_close_model() # Ensure model cleanup runs
                    # Explicitly stop the interactor if needed, though QtInteractor might manage this
                    if hasattr(self.plotter, 'interactor') and hasattr(self.plotter.interactor, 'TerminateApp'):
                         self.plotter.interactor.TerminateApp()
                except Exception as e:
                    print(f"[WARN] Error during plotter cleanup on exit: {e}")
            print("   Accepting close event.")
            event.accept() # Proceed with closing
        else:
            print("   User cancelled exit.")
            event.ignore() # Cancel the close


# --- Application Entry Point ---
if __name__ == "__main__":
    print("=" * 60)
    print(f"   Starting {APP_NAME} v{APP_VERSION}")
    print("=" * 60)

    # --- Qt Application Setup ---
    # Enable High DPI scaling if available
    # Note: AA_EnableHighDpiScaling and AA_UseHighDpiPixmaps are deprecated in newer Qt versions
    # but may be necessary for compatibility with older versions or specific systems.
    try:
        if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
            print("[Qt Setup] Enabled High DPI Scaling (Deprecated).")
        if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
            QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
            print("[Qt Setup] Enabled High DPI Pixmaps (Deprecated).")
    except Exception as e:
        print(f"[WARN] Could not set High DPI attributes: {e}")

    # Create the QApplication object
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME) # Used for QSettings if implemented
    app.setApplicationVersion(APP_VERSION)

    # --- Create and Show Main Window ---
    print("\n[MAIN] Creating main window...")
    main_window = ProfessionalViewerMainWindow()
    print("[MAIN] Showing main window...")
    main_window.show() # Make the window visible

    # --- Start the Event Loop ---
    print("\n[MAIN] Starting Qt event loop...")
    exit_code = app.exec() # Blocks until the application is terminated

    print("\n[MAIN] Qt event loop finished.")
    sys.exit(exit_code) # Exit the program with the appropriate exit code
