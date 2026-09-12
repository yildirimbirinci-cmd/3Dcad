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




-- ============================================================
-- CAD3D_MAX_CONNECT_MOVE_V1
-- Reads CONNECT_LEVEL_CM from the current Python request.
-- Targets are FLOOR-LOCAL Z values. BASE_Z is never added here.
-- ============================================================

fn CAD3D_ReadConnectLevelsV1 filePath =
(
    local result = #()
    local stream = openFile filePath mode:"rt"

    if stream == undefined then return result

    while not eof stream do
    (
        local line = readLine stream

        if line != undefined do
        (
            if matchPattern line pattern:"CONNECT_LEVEL_CM=*" do
            (
                if line.count > 17 do
                (
                    local rawValue = substring line 18 (line.count - 17)
                    local value = undefined

                    try
                    (
                        value = rawValue as float
                    )
                    catch
                    (
                        value = undefined
                    )

                    if value != undefined do append result value
                )
            )
        )
    )

    close stream

    sort result

    local uniqueValues = #()

    for value in result do
    (
        if uniqueValues.count == 0 then
        (
            append uniqueValues value
        )
        else
        (
            if abs (value - uniqueValues[uniqueValues.count]) > 0.000001 do
            (
                append uniqueValues value
            )
        )
    )

    uniqueValues
)


fn CAD3D_ConnectAtLocalZV1 ep node targetCm wallHeightCm =
(
    local cmUnit = units.decodeValue "1cm"
    local targetZ = targetCm * cmUnit
    local wallTopZ = wallHeightCm * cmUnit

    local axisTol = units.decodeValue "0.01mm"
    local zTol = units.decodeValue "0.5mm"
    local minVertical = units.decodeValue "1mm"
    local minHorizontal = units.decodeValue "1mm"

    if targetZ <= zTol then return true
    if targetZ >= (wallTopZ - zTol) then return true

    local edgeCountBefore = ep.GetNumEdges node:node
    local selectedVertical = #{}

    for edgeIndex = 1 to edgeCountBefore do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dx = abs (pb.x - pa.x)
            local dy = abs (pb.y - pa.y)
            local dz = abs (pb.z - pa.z)

            if ((dx <= axisTol) and (dy <= axisTol) and (dz > minVertical)) do
            (
                local zMin = amin pa.z pb.z
                local zMax = amax pa.z pb.z

                if ((targetZ > (zMin + zTol)) and (targetZ < (zMax - zTol))) do
                (
                    selectedVertical[edgeIndex] = true
                )
            )
        )
    )

    if selectedVertical.numberSet <= 0 then
    (
        format "3Dcad Connect ERROR | target=% cm | vertical edge not found\n" targetCm
        return false
    )

    -- CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2
    -- Proven selection contract:
    -- clear -> Select -> authoritative GetSelection readback.
    local emptyEdgeSelection = #{}
    ep.SetSelection #Edge &emptyEdgeSelection node:node

    local edgeSelection = selectedVertical
    local edgeSelectOK = ep.Select #Edge &edgeSelection select:true node:node
    local selectedReadback = ep.GetSelection #Edge node:node

    if ((edgeSelectOK != true) or (selectedReadback.numberSet != selectedVertical.numberSet)) then
    (
        format "3Dcad Connect ERROR | target=% cm | vertical selection failed | wanted=% selected=%\n" targetCm selectedVertical.numberSet selectedReadback.numberSet
        return false
    )

    format "3Dcad Connect vertical selection | target=% cm | selected=%\n" targetCm selectedReadback.numberSet

    ep.connectEdgeSegments = 1
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0

    ep.ButtonOp #ConnectEdges
    ep.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = ep.GetNumEdges node:node

    if edgeCountAfter <= edgeCountBefore then
    (
        format "3Dcad Connect ERROR | target=% cm | no new topology\n" targetCm
        return false
    )

    local newHorizontal = #{}
    local generatedZSum = 0.0
    local generatedZCount = 0

    for edgeIndex = (edgeCountBefore + 1) to edgeCountAfter do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dx = pb.x - pa.x
            local dy = pb.y - pa.y
            local dz = abs (pb.z - pa.z)
            local horizontalLength = sqrt ((dx * dx) + (dy * dy))

            if ((dz <= zTol) and (horizontalLength > minHorizontal)) do
            (
                newHorizontal[edgeIndex] = true
                generatedZSum += ((pa.z + pb.z) * 0.5)
                generatedZCount += 1
            )
        )
    )

    if ((newHorizontal.numberSet <= 0) or (generatedZCount <= 0)) then
    (
        format "3Dcad Connect ERROR | target=% cm | new horizontal edge not found\n" targetCm
        return false
    )

    local generatedZ = generatedZSum / generatedZCount
    local deltaZ = targetZ - generatedZ

    -- CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2
    -- Select actual newly-created horizontal Connect edges with
    -- clear -> Select -> readback, then use the proven transform contract.
    local clearNewEdges = #{}
    ep.SetSelection #Edge &clearNewEdges node:node

    local newSelection = newHorizontal
    local newSelectOK = ep.Select #Edge &newSelection select:true node:node
    local newReadback = ep.GetSelection #Edge node:node

    if ((newSelectOK != true) or (newReadback.numberSet != newHorizontal.numberSet)) then
    (
        format "3Dcad Connect ERROR | target=% cm | new horizontal selection failed | wanted=% selected=%\n" targetCm newHorizontal.numberSet newReadback.numberSet
        return false
    )

    local deltaVector = [0,0,deltaZ]

    ep.useSoftSel = false
    ep.SetOperation #Transform
    ep.MoveSelection deltaVector
    ep.Commit()

    ep.RefreshScreen()
    completeRedraw()

    local finalOK = true

    for edgeIndex = 1 to edgeCountAfter while finalOK do
    (
        if newHorizontal[edgeIndex] do
        (
            local va = ep.GetEdgeVertex edgeIndex 1 node:node
            local vb = ep.GetEdgeVertex edgeIndex 2 node:node

            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            if abs (pa.z - targetZ) > zTol do finalOK = false
            if abs (pb.z - targetZ) > zTol do finalOK = false
        )
    )

    if finalOK != true then
    (
        format "3Dcad Connect ERROR | target=% cm | final Z verification failed\n" targetCm
        return false
    )

    format "3Dcad Connect moved | target=% cm | generated=% | delta=% | edges=%\n" targetCm generatedZ deltaZ newHorizontal.numberSet

    true
)


fn CAD3D_ApplyConnectLevelsV1 node levels wallHeightCm =
(
    if levels.count <= 0 then return true

    local ep = Edit_Poly()
    addModifier node ep

    -- CAD3D_MAX_CONNECT_PROVEN_SELECTION_V2
    -- Mirror the previously proven CAD_to_3D_Max Edit Poly setup.
    max modify mode
    select node

    ep.SetPrimaryNode node
    modPanel.setCurrentObject ep

    ep.selectMode = 1
    ep.SetEPolySelLevel #Edge
    subObjectLevel = 2

    ep.RefreshScreen()
    completeRedraw()

    format "\n========================================\n"
    format "3DCAD MAX CONNECT MOVE V1\n"
    format "Levels: %\n" levels

    for targetCm in levels do
    (
        local ok = CAD3D_ConnectAtLocalZV1 ep node targetCm wallHeightCm

        if ok != true then
        (
            format "FAILED LEVEL: % cm\n" targetCm
            format "========================================\n\n"
            return false
        )
    )

    format "Connect levels completed: %\n" levels.count
    format "========================================\n\n"

    true
)




-- ============================================================
-- CAD3D_MAX_CONNECT_BATCH_V3
--
-- One Connect operation creates ALL requested horizontal bands.
-- Then every generated band is moved to its exact target local Z.
--
-- This avoids sequential Connect operations on already split vertical
-- edges, which caused the second level to fail verification.
-- ============================================================

fn CAD3D_ApplyConnectLevelsBatchV3 node levels wallHeightCm =
(
    if levels.count <= 0 then return true

    local cmUnit = units.decodeValue "1cm"
    local axisTol = units.decodeValue "0.01mm"
    local zTol = units.decodeValue "0.5mm"
    local minVertical = units.decodeValue "1mm"
    local minHorizontal = units.decodeValue "1mm"

    local ep = Edit_Poly()
    addModifier node ep

    max modify mode
    select node

    ep.SetPrimaryNode node
    modPanel.setCurrentObject ep

    ep.selectMode = 1
    ep.SetEPolySelLevel #Edge
    subObjectLevel = 2

    ep.RefreshScreen()
    completeRedraw()

    local edgeCountBefore = ep.GetNumEdges node:node
    local verticalEdges = #{}

    for edgeIndex = 1 to edgeCountBefore do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dx = abs (pb.x - pa.x)
            local dy = abs (pb.y - pa.y)
            local dz = abs (pb.z - pa.z)

            if ((dx <= axisTol) and (dy <= axisTol) and (dz > minVertical)) do
            (
                verticalEdges[edgeIndex] = true
            )
        )
    )

    if verticalEdges.numberSet <= 0 then
    (
        format "3Dcad Connect ERROR | no vertical edges found\n"
        return false
    )

    local clearEdges = #{}
    ep.SetSelection #Edge &clearEdges node:node

    local selectOK = ep.Select #Edge &verticalEdges select:true node:node
    local readback = ep.GetSelection #Edge node:node

    if ((selectOK != true) or (readback.numberSet != verticalEdges.numberSet)) then
    (
        format "3Dcad Connect ERROR | vertical selection failed | wanted=% selected=%\n" verticalEdges.numberSet readback.numberSet
        return false
    )

    ep.connectEdgeSegments = levels.count
    ep.connectEdgePinch = 0
    ep.connectEdgeSlide = 0

    format "\n========================================\n"
    format "3DCAD MAX CONNECT BATCH V3\n"
    format "Levels: %\n" levels
    format "Vertical edges selected: %\n" readback.numberSet
    format "Connect segments: %\n" levels.count

    ep.ButtonOp #ConnectEdges
    ep.RefreshScreen()
    completeRedraw()

    local edgeCountAfter = ep.GetNumEdges node:node

    if edgeCountAfter <= edgeCountBefore then
    (
        format "3Dcad Connect ERROR | batch Connect created no new topology\n"
        return false
    )

    local groups = #()

    for edgeIndex = (edgeCountBefore + 1) to edgeCountAfter do
    (
        local va = ep.GetEdgeVertex edgeIndex 1 node:node
        local vb = ep.GetEdgeVertex edgeIndex 2 node:node

        if ((va > 0) and (vb > 0)) do
        (
            local pa = ep.GetVertex va node:node
            local pb = ep.GetVertex vb node:node

            local dx = pb.x - pa.x
            local dy = pb.y - pa.y
            local dz = abs (pb.z - pa.z)
            local horizontalLength = sqrt ((dx * dx) + (dy * dy))

            if ((dz <= zTol) and (horizontalLength > minHorizontal)) do
            (
                local edgeZ = (pa.z + pb.z) * 0.5
                local foundGroup = 0

                for groupIndex = 1 to groups.count while foundGroup == 0 do
                (
                    if abs (groups[groupIndex][1] - edgeZ) <= zTol do
                    (
                        foundGroup = groupIndex
                    )
                )

                if foundGroup == 0 then
                (
                    local bits = #{}
                    bits[edgeIndex] = true
                    append groups #(edgeZ, bits)
                )
                else
                (
                    groups[foundGroup][2][edgeIndex] = true
                )
            )
        )
    )

    if groups.count != levels.count then
    (
        format "3Dcad Connect ERROR | generated band count mismatch | expected=% actual=%\n" levels.count groups.count
        return false
    )

    -- Sort generated groups by Z ascending.
    for i = 1 to (groups.count - 1) do
    (
        for j = (i + 1) to groups.count do
        (
            if groups[j][1] < groups[i][1] do
            (
                local temp = groups[i]
                groups[i] = groups[j]
                groups[j] = temp
            )
        )
    )

    -- Levels were already sorted by the Python request reader.
    -- Move every generated band to the matching exact target Z.
    for levelIndex = 1 to levels.count do
    (
        local targetCm = levels[levelIndex]
        local targetZ = targetCm * cmUnit

        local generatedZ = groups[levelIndex][1]
        local bandEdges = groups[levelIndex][2]
        local deltaZ = targetZ - generatedZ

        local clearBand = #{}
        ep.SetSelection #Edge &clearBand node:node

        local bandSelection = bandEdges
        local bandSelectOK = ep.Select #Edge &bandSelection select:true node:node
        local bandReadback = ep.GetSelection #Edge node:node

        if ((bandSelectOK != true) or (bandReadback.numberSet != bandEdges.numberSet)) then
        (
            format "3Dcad Connect ERROR | target=% cm | band selection failed | wanted=% selected=%\n" targetCm bandEdges.numberSet bandReadback.numberSet
            return false
        )

        local deltaVector = [0,0,deltaZ]

        ep.useSoftSel = false
        ep.SetOperation #Transform
        ep.MoveSelection deltaVector
        ep.Commit()

        ep.RefreshScreen()
        completeRedraw()

        local firstEdge = 0

        for edgeIndex = 1 to edgeCountAfter while firstEdge == 0 do
        (
            if bandEdges[edgeIndex] do firstEdge = edgeIndex
        )

        if firstEdge <= 0 then
        (
            format "3Dcad Connect ERROR | target=% cm | band edge missing after move\n" targetCm
            return false
        )

        local checkVA = ep.GetEdgeVertex firstEdge 1 node:node
        local checkVB = ep.GetEdgeVertex firstEdge 2 node:node
        local checkPA = ep.GetVertex checkVA node:node
        local checkPB = ep.GetVertex checkVB node:node

        if (
            (abs (checkPA.z - targetZ) > zTol) or
            (abs (checkPB.z - targetZ) > zTol)
        ) then
        (
            format "3Dcad Connect ERROR | target=% cm | final Z verification failed | A=% B=% expected=%\n" targetCm checkPA.z checkPB.z targetZ
            return false
        )

        format "3Dcad Connect moved | target=% cm | generated=% | delta=% | edges=%\n" targetCm generatedZ deltaZ bandEdges.numberSet
    )

    format "Connect levels completed: %\n" levels.count
    format "========================================\n\n"

    true
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

    -- ========================================================
    -- CAD3D_EXTRUDE_ONLY_V1
    --
    -- CAD_to_3D_Max proven Extrude contract:
    -- - flat/closed spline remains the base object
    -- - wall height comes from HEIGHT_CM
    -- - physical centimeters are converted to Max system units
    -- - Extrude remains a LIVE modifier
    -- - no Edit Poly
    -- - no Connect
    -- - no door/window topology operation
    -- ========================================================

    if isV2 then
    (
        if heightCm <= 0.0 then
        (
            delete shapeNode
            format "3Dcad bridge: invalid wall height for Extrude: % cm\n" heightCm
            return false
        )

        local heightSystemUnits = heightCm * (units.decodeValue "1cm")

        local extrudeMod = Extrude()

        extrudeMod.amount = heightSystemUnits
        extrudeMod.segments = 1
        extrudeMod.capStart = true
        extrudeMod.capEnd = true

        addModifier shapeNode extrudeMod

        -- CAD3D_MAX_CONNECT_MOVE_V1
        local connectLevelsCm = CAD3D_ReadConnectLevelsV1 filePath
        if connectLevelsCm.count > 0 then
        (
            local connectOK = CAD3D_ApplyConnectLevelsBatchV3 shapeNode connectLevelsCm heightCm
            if connectOK != true do
            (
                throw "CAD3D_VERTICAL_CONNECT_FAILED"
            )
        )


        format "3Dcad Extrude added | height=% cm | segments=1 | caps=ON\n" heightCm
    )

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

