import rhinoscriptsyntax as rs
import System
import Rhino
import Eto.Drawing as drawing
import Eto.Forms as forms

html_string = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body { 
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
        padding: 20px; 
        background-color: #f7f7f7;
        color: #333;
    }
    h2 { margin-top: 0; }
    .slider-container { 
        margin-bottom: 20px; 
        background: #fff;
        padding: 10px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    input[type=range] { 
        width: 100%; 
        margin-top: 10px;
    }
    button { 
        background-color: #0078d7;
        color: white;
        padding: 12px 20px; 
        font-size: 16px; 
        width: 100%; 
        cursor: pointer;
        border: none;
        border-radius: 8px;
        font-weight: bold;
        transition: background-color 0.2s;
    }
    button:hover {
        background-color: #005a9e;
    }
    .val-display {
        float: right;
        font-weight: bold;
        color: #0078d7;
    }
</style>
<script>
    let updateTimeout = null;
    const THROTTLE_MS = 30;

    function sendUpdate() {
        var l = document.getElementById('l').value;
        var w = document.getElementById('w').value;
        var h = document.getElementById('h').value;
        document.getElementById('l_val').innerText = l;
        document.getElementById('w_val').innerText = w;
        document.getElementById('h_val').innerText = h;
        
        // Throttle the actual navigation to avoid choking Rhino
        if (!updateTimeout) {
            updateTimeout = setTimeout(() => {
                window.location.href = "http://rhino-update/?l=" + l + "&w=" + w + "&h=" + h;
                updateTimeout = null;
            }, THROTTLE_MS);
        }
    }
    function createCube() {
        window.location.href = "http://rhino-create/";
    }
</script>
</head>
<body>
    <h2>Create Cube</h2>
    <div class="slider-container">
        <label>Length: <span id="l_val" class="val-display">10</span></label>
        <input type="range" id="l" min="1" max="999" value="10" oninput="sendUpdate()">
    </div>
    <div class="slider-container">
        <label>Width: <span id="w_val" class="val-display">10</span></label>
        <input type="range" id="w" min="1" max="999" value="10" oninput="sendUpdate()">
    </div>
    <div class="slider-container">
        <label>Height: <span id="h_val" class="val-display">10</span></label>
        <input type="range" id="h" min="1" max="999" value="10" oninput="sendUpdate()">
    </div>
    <button onclick="createCube()">create cube!</button>
</body>
</html>
"""

class CubeConduit(Rhino.Display.DisplayConduit):
    def __init__(self, l, w, h):
        super(CubeConduit, self).__init__()
        self.l = l
        self.w = w
        self.h = h
        self.color = System.Drawing.Color.FromArgb(0, 120, 215)
        self.color = System.Drawing.Color.FromArgb(0, 120, 215)
        
    def CalculateBoundingBox(self, e):
        # We need to tell Rhino how big our custom drawing is so it doesn't get culled
        bbox = Rhino.Geometry.BoundingBox(0, 0, 0, self.l, self.w, self.h)
        e.IncludeBoundingBox(bbox)
        
    def PostDrawObjects(self, e):
        # Draw the 12 edges of the box
        pt0 = Rhino.Geometry.Point3d(0, 0, 0)
        pt1 = Rhino.Geometry.Point3d(self.l, 0, 0)
        pt2 = Rhino.Geometry.Point3d(self.l, self.w, 0)
        pt3 = Rhino.Geometry.Point3d(0, self.w, 0)
        
        pt4 = Rhino.Geometry.Point3d(0, 0, self.h)
        pt5 = Rhino.Geometry.Point3d(self.l, 0, self.h)
        pt6 = Rhino.Geometry.Point3d(self.l, self.w, self.h)
        pt7 = Rhino.Geometry.Point3d(0, self.w, self.h)
        
        # Bottom rectangle
        e.Display.DrawLine(pt0, pt1, self.color, 2)
        e.Display.DrawLine(pt1, pt2, self.color, 2)
        e.Display.DrawLine(pt2, pt3, self.color, 2)
        e.Display.DrawLine(pt3, pt0, self.color, 2)
        
        # Top rectangle
        e.Display.DrawLine(pt4, pt5, self.color, 2)
        e.Display.DrawLine(pt5, pt6, self.color, 2)
        e.Display.DrawLine(pt6, pt7, self.color, 2)
        e.Display.DrawLine(pt7, pt4, self.color, 2)
        
        # Vertical edges
        e.Display.DrawLine(pt0, pt4, self.color, 2)
        e.Display.DrawLine(pt1, pt5, self.color, 2)
        e.Display.DrawLine(pt2, pt6, self.color, 2)
        e.Display.DrawLine(pt3, pt7, self.color, 2)

class HtmlCubeDialog(forms.Dialog):
    def __init__(self):
        super(HtmlCubeDialog, self).__init__()
        self.Title = "Interactive Cube (HTML)"
        self.ClientSize = drawing.Size(350, 420)
        self.Resizable = False

        self.l = 10.0
        self.w = 10.0
        self.h = 10.0

        # Initialize and enable the conduit
        self.conduit = CubeConduit(self.l, self.w, self.h)
        self.conduit.Enabled = True

        self.webview = forms.WebView()
        self.webview.LoadHtml(html_string)
        self.webview.DocumentLoading += self.OnDocumentLoading
        
        self.Content = self.webview
        self.Closed += self.OnFormClosed
        
        Rhino.RhinoDoc.ActiveDoc.Views.Redraw()
        
    def OnDocumentLoading(self, sender, e):
        # Intercept navigation to communicate with Python
        uri = e.Uri.ToString()
        if "rhino-update" in uri:
            e.Cancel = True # Stop actual navigation
            try:
                # Parse arguments
                query = uri.split('?')[1]
                args = dict(q.split('=') for q in query.split('&'))
                self.l = float(args.get('l', 10))
                self.w = float(args.get('w', 10))
                self.h = float(args.get('h', 10))
                self.UpdatePreview()
            except Exception as ex:
                rs.Prompt("Error updating: " + str(ex))
                
        elif "rhino-create" in uri:
            e.Cancel = True
            self.CreateAndClose()
                
    def UpdatePreview(self):
        # Simply update the conduit parameters and redraw
        self.conduit.l = self.l
        self.conduit.w = self.w
        self.conduit.h = self.h
        Rhino.RhinoDoc.ActiveDoc.Views.Redraw()

    def CreateAndClose(self):
        # Disable conduit, bake final geometry, and close
        self.conduit.Enabled = False
        Rhino.RhinoDoc.ActiveDoc.Views.Redraw()
        
        pts = [
            [0,0,0], [self.l, 0, 0], [self.l, self.w, 0], [0, self.w, 0],
            [0,0,self.h], [self.l, 0, self.h], [self.l, self.w, self.h], [0, self.w, self.h]
        ]
        rs.AddBox(pts)
        
        self.Close(True)
        
    def OnFormClosed(self, sender, e):
        # Ensure conduit is disabled if user cancels via X button
        self.conduit.Enabled = False
        Rhino.RhinoDoc.ActiveDoc.Views.Redraw()

def run():
    # Make sure we're in the right context
    if rs.DocumentModified() is not None:
        dlg = HtmlCubeDialog()
        dlg.ShowModal(Rhino.UI.RhinoEtoApp.MainWindow)
    else:
        print("Error: No active Rhino document.")

if __name__ == "__main__":
    run()
