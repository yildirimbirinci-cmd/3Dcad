/*
3Dcad -> 3ds Max Wall Bridge V1

- Watches visible_cad_request.txt
- Receives ONLY selected wall primitives
- Input coordinates are physical millimeters
- CAD pivot is subtracted from every XY coordinate
- Result node world position = [0,0,0]
*/

global CAD3DcadBridgeTimer
global CAD3DcadBridgeLastRequestId = ""

global CAD3DcadScriptFile = getSourceFileName()
global CAD3DcadScriptDir = getFilenamePath CAD3DcadScriptFile
global CAD3DcadProjectRoot = pathConfig.appendPath CAD3DcadScriptDir ".."
global CAD3DcadRequestFile = pathConfig.appendPath CAD3DcadProjectRoot "data\cache\max_bridge\visible_cad_request.txt"


fn CAD3D_ReadRequestId filePath =
(
    if not (doesFileExist filePath) then return ""

    local stream = openFile filePath mode:"rt"

    if stream == undefined then return ""

    local header = readLine stream
    local result = ""

    while not (eof stream) do
    (
        local line = readLine stream

        if line != undefined then
        (
            if matchPattern line pattern:"REQUEST_ID=*" then
            (
                result = substring line 12 (line.count - 11)
                exit
            )
        )
    )

    close stream

    result
)


fn CAD3D_ReadOption lines prefix =
(
    for line in lines do
    (
        if matchPattern line pattern:(prefix + "*") then
        (
            return substring line (prefix.count + 1) (line.count - prefix.count)
        )
    )

    undefined
)


fn CAD3D_CleanImportedSpline shapeNode =
(
    /*
    3Dcad -> Max vertex cleanup

    Spline Max'e olusturulduktan sonra:
    - tum knot'lar secilir
    - birbirine cok yakin knot'lar weld edilir
    - kaynak 3Dcad/CAD geometrisine dokunulmaz
    */

    local weldTolerance = units.decodeValue "0.1mm"

    updateShape shapeNode

    for splineIndex = 1 to (numSplines shapeNode) do
    (
        local knotCount = numKnots shapeNode splineIndex

        if knotCount > 1 then
        (
            local knotSelection = #()

            for knotIndex = 1 to knotCount do
            (
                append knotSelection knotIndex
            )

            setKnotSelection shapeNode splineIndex knotSelection keep:false
        )
    )

    weldSpline shapeNode weldTolerance

    updateShape shapeNode

    -- Selection cleanup
    for splineIndex = 1 to (numSplines shapeNode) do
    (
        setKnotSelection shapeNode splineIndex #() keep:false
    )

    updateShape shapeNode

    format "3Dcad vertex cleanup | weld tolerance: 0.1 mm\n"
)

fn CAD3D_ImportWalls filePath =
(
    if not (doesFileExist filePath) then return false

    local stream = openFile filePath mode:"rt"

    if stream == undefined then return false

    local header = readLine stream

    if header != "3DCAD_WALL_REQUEST_V1" then
    (
        close stream
        format "3Dcad bridge: invalid request header.\n"
        return false
    )

    local rows = #()

    while not (eof stream) do
    (
        local line = readLine stream

        if line != undefined and line != "" do
        (
            append rows line
        )
    )

    close stream

    local pivotXText = CAD3D_ReadOption rows "PIVOT_X_MM="
    local pivotYText = CAD3D_ReadOption rows "PIVOT_Y_MM="

    if pivotXText == undefined or pivotYText == undefined then
    (
        format "3Dcad bridge: pivot metadata missing.\n"
        return false
    )

    local pivotX = pivotXText as float
    local pivotY = pivotYText as float

    local oldNode = getNodeByName "3Dcad_Walls"

    if oldNode != undefined do delete oldNode

    local shapeNode = splineShape name:"3Dcad_Walls"
    shapeNode.wirecolor = color 0 140 255

    local splineCount = 0
    local mmUnit = units.decodeValue "1mm"

    for line in rows do
    (
        if matchPattern line pattern:"S|*" then
        (
            local parts = filterString line "|"

            if parts.count >= 3 then
            (
                local closedFlag = parts[2] as integer
                local pointsText = parts[3]

                local pointRows = filterString pointsText ";"

                if pointRows.count >= 2 then
                (
                    addNewSpline shapeNode
                    splineCount += 1

                    for pointText in pointRows do
                    (
                        local xy = filterString pointText ","

                        if xy.count >= 2 then
                        (
                            local xMM = xy[1] as float
                            local yMM = xy[2] as float

                            local localX = (xMM - pivotX) * mmUnit
                            local localY = (yMM - pivotY) * mmUnit

                            addKnot shapeNode splineCount #corner #line [localX,localY,0]
                        )
                    )

                    if closedFlag == 1 do
                    (
                        close shapeNode splineCount
                    )
                )
            )
        )
    )

    updateShape shapeNode

    shapeNode.position = [0,0,0]

    select shapeNode
    completeRedraw()

    format "\n"
    format "========================================\n"
    format "3Dcad WALL BRIDGE V1\n"
    format "Wall splines : %\n" splineCount
    format "Pivot CAD mm : X=% Y=%\n" pivotX pivotY
    format "Node world   : 0,0,0\n"
    format "========================================\n"
    format "\n"

    true
)


fn CAD3D_OnTick sender args =
(
    local requestId = CAD3D_ReadRequestId CAD3DcadRequestFile

    if requestId != "" and requestId != CAD3DcadBridgeLastRequestId then
    (
        CAD3DcadBridgeLastRequestId = requestId

        try
        (
            CAD3D_ImportWalls CAD3DcadRequestFile
        )
        catch
        (
            format "\n3Dcad bridge ERROR:\n%\n" (getCurrentException())
        )
    )
)


try
(
    if CAD3DcadBridgeTimer != undefined do
    (
        CAD3DcadBridgeTimer.Stop()
    )
)
catch()


CAD3DcadBridgeLastRequestId = CAD3D_ReadRequestId CAD3DcadRequestFile

CAD3DcadBridgeTimer = dotNetObject "System.Windows.Forms.Timer"
CAD3DcadBridgeTimer.Interval = 500

dotNet.addEventHandler CAD3DcadBridgeTimer "Tick" CAD3D_OnTick
CAD3DcadBridgeTimer.Start()


format "\n"
format "========================================\n"
format "3Dcad MAX BRIDGE ACTIVE V1\n"
format "Request: %\n" CAD3DcadRequestFile
format "========================================\n"
format "\n"
