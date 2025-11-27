Option Explicit

Sub UpdateTocAndExport()
    Const INPUT_PATH As String = "/config/input.docx"
    Dim oDocument As Object
    Dim dispatcher As Object
    Dim props(0) As New com.sun.star.beans.PropertyValue
    Dim sPdfPath As String
    Dim nDotPos As Long
    Dim nLog As Integer

    ' Optional lightweight logging for debugging
    nLog = FreeFile
    On Error Resume Next
    Open "/config/macro.log" For Append As #nLog
    Print #nLog, "----"
    Print #nLog, "INPUT_PATH=" & INPUT_PATH
    Close #nLog
    On Error GoTo 0

    ' Open the document from a fixed absolute file system path
    oDocument = StarDesktop.loadComponentFromURL( _
        ConvertToURL(INPUT_PATH), "_blank", 0, Array())

    If IsNull(oDocument) Then Exit Sub

    ' Update all indexes (including table of contents)
    dispatcher = createUnoService("com.sun.star.frame.DispatchHelper")
    dispatcher.executeDispatch( _
        oDocument.CurrentController.Frame, _
        ".uno:UpdateAllIndexes", "", 0, Array())

    ' Save the DOCX back to the same path
    oDocument.store()

    ' Export a PDF next to the DOCX
    props(0).Name = "FilterName"
    props(0).Value = "writer_pdf_Export"

    nDotPos = InStrRev(INPUT_PATH, ".")
    If nDotPos > 0 Then
        sPdfPath = Left$(INPUT_PATH, nDotPos - 1) & ".pdf"
    Else
        sPdfPath = INPUT_PATH & ".pdf"
    End If

    nLog = FreeFile
    On Error Resume Next
    Open "/config/macro.log" For Append As #nLog
    Print #nLog, "Export sPdfPath=" & sPdfPath
    Close #nLog
    On Error GoTo 0

    oDocument.storeToURL(ConvertToURL(sPdfPath), props())
    oDocument.close(True)
End Sub
