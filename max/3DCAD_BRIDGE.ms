/*
3Dcad -> 3ds Max Wall Bridge V2

CAD_to_3D_Max proven floor transfer contract:
- each floor has its own CAD XY pivot
- CAD XY is made local by subtracting that pivot
- BASE_Z_CM controls world Z
- each floor has a separate Max node
- previous same-floor node is replaced only after new import succeeds
- result file confirms success before Python sends next floor
*/

global CAD3DcadBridgeTimer
global CAD3DcadBridgeLastRequestId = ""
global CAD3DcadScriptFile = getSourceFileName()
global CAD3DcadScriptDir = getFilenamePath CAD3DcadScriptFile
global CAD3DcadProjectRoot = pathConfig.appendPath CAD3DcadScriptDir ".."
global CAD3DcadRequestFile = pathConfig.appendPath CAD3DcadProjectRoot "data\cache\max_bridge\visible_cad_request.txt"
global CAD3DcadResultFile = pathConfig.appendPath CAD3DcadProjectRoot "data\cache\max_bridge\visible_cad_result.txt"


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


fn CAD3D_WriteResult requestId statusText messageText =
(
    local tempPath = CAD3DcadResultFile + ".tmp"
    local stream = createFile tempPath

    if stream == undefined then return false

    format "3DCAD_WALL_RESULT_V2\n" to:stream
    format "REQUEST_ID=%\n" requestId to:stream
    format "STATUS=%\n" statusText to:stream
    format "MESSAGE=%\n" messageText to:stream

    close stream

    if doesFileExist CAD3DcadResultFile do
    (
        deleteFile CAD3DcadResultFile
    )

    renameFile tempPath CAD3DcadResultFile
    true
)


fn CAD3D_CleanImportedSpline shapeNode =
(
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

    for splineIndex = 1 to (numSplines shapeNode) do
    (
        setKnotSelection shapeNode splineIndex #() keep:false
    )

    updateShape shapeNode
)


fn CAD3D_ImportWalls filePath =
(
    if not (doesFileExist filePath) then return false

    local stream = openFile filePath mode:"rt"
    if stream == undefined then return false

    local header = readLine stream

    local isV1 = (findString header "3DCAD_WALL_REQUEST_V1" != undefined)
    local isV2 = (findString header "3DCAD_WALL_REQUEST_V2" != undefined)

    if not isV1 and not isV2 then
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

    local requestId = CAD3D_ReadOption rows "REQUEST_ID="
    local pivotXText = CAD3D_ReadOption rows "PIVOT_X_MM="
    local pivotYText = CAD3D_ReadOption rows "PIVOT_Y_MM="

    if requestId == undefined then
    (
        format "3Dcad bridge: request id missing.\n"
        return false
    )

    if pivotXText == undefined or pivotYText == undefined then
    (
        format "3Dcad bridge: pivot metadata missing.\n"
        return false
    )

    local pivotX = pivotXText as float
    local pivotY = pivotYText as float

    local floorName = ""
    local floorIndexText = ""
    local baseZ = 0.0
    local heightCm = 0.0
    local interfloorCm = 0.0
    local nodeName = "3Dcad_Walls"

    if isV2 then
    (
        local floorNameText = CAD3D_ReadOption rows "FLOOR_NAME="
        local floorIndexValue = CAD3D_ReadOption rows "FLOOR_INDEX="
        local baseZText = CAD3D_ReadOption rows "BASE_Z_CM="
        local heightText = CAD3D_ReadOption rows "HEIGHT_CM="
        local interfloorText = CAD3D_ReadOption rows "INTERFLOOR_CM="
        local nodeNameText = CAD3D_ReadOption rows "NODE_NAME="

        if floorNameText != undefined do floorName = floorNameText
        if floorIndexValue != undefined do floorIndexText = floorIndexValue
        if baseZText != undefined do baseZ = baseZText as float
        if heightText != undefined do heightCm = heightText as float
        if interfloorText != undefined do interfloorCm = interfloorText as float
        if nodeNameText != undefined do nodeName = nodeNameText
    )

    local tempNodeName = "__3Dcad_TEMP_" + requestId
    local staleTemp = getNodeByName tempNodeName

    if staleTemp != undefined do
    (
        delete staleTemp
    )

    local shapeNode = splineShape name:tempNodeName
    shapeNode.wirecolor = color 0 140 255

    local splineCount = 0
    local mmUnit = units.decodeValue "1mm"
    local cmUnit = units.decodeValue "1cm"

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

    if splineCount <= 0 then
    (
        delete shapeNode
        format "3Dcad bridge: no wall splines.\n"
        return false
    )

    updateShape shapeNode

    shapeNode.position = point3 0 0 (baseZ * cmUnit)

    try
    (
        setUserProp shapeNode "FloorName" floorName
        setUserProp shapeNode "FloorIndex" floorIndexText
        setUserProp shapeNode "BaseZCm" (baseZ as string)
        setUserProp shapeNode "WallHeightCm" (heightCm as string)
        setUserProp shapeNode "InterfloorCm" (interfloorCm as string)
        setUserProp shapeNode "PivotXMM" (pivotX as string)
        setUserProp shapeNode "PivotYMM" (pivotY as string)
    )
    catch()

    local oldNode = getNodeByName nodeName

    if oldNode != undefined and oldNode != shapeNode do
    (
        delete oldNode
    )

    shapeNode.name = nodeName

    select shapeNode
    completeRedraw()

    format "\n"
    format "========================================\n"
    format "3Dcad WALL BRIDGE V2\n"
    format "Floor        : %\n" floorName
    format "Floor index  : %\n" floorIndexText
    format "Node         : %\n" nodeName
    format "Wall splines : %\n" splineCount
    format "Pivot CAD mm : X=% Y=%\n" pivotX pivotY
    format "BASE Z cm    : %\n" baseZ
    format "Wall height  : % cm\n" heightCm
    format "Interfloor   : % cm\n" interfloorCm
    format "Node world   : 0,0,% cm\n" baseZ
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
            local ok = CAD3D_ImportWalls CAD3DcadRequestFile

            if ok then
            (
                CAD3D_WriteResult requestId "OK" "OK"
            )
            else
            (
                CAD3D_WriteResult requestId "ERROR" "IMPORT_FAILED"
            )
        )
        catch
        (
            format "\n3Dcad bridge ERROR:\n%\n" (getCurrentException())
            CAD3D_WriteResult requestId "ERROR" "MAXSCRIPT_EXCEPTION"
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
format "3Dcad MAX BRIDGE ACTIVE V2 - MULTI FLOOR\n"
format "Request: %\n" CAD3DcadRequestFile
format "Result : %\n" CAD3DcadResultFile
format "========================================\n"
format "\n"

