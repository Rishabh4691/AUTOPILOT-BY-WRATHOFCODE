param([Parameter(Mandatory = $true)][string]$Wav)
Add-Type -AssemblyName System.Speech
$engine = $null
foreach ($culture in @('en-US', 'en-GB', 'de-DE')) {
    try {
        $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine([System.Globalization.CultureInfo]$culture)
        break
    } catch { }
}
if ($null -eq $engine) { $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine }
$engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$engine.SetInputToWaveFile($Wav)
$words = @()
while ($true) {
    $result = $engine.Recognize()
    if ($null -eq $result) { break }
    $words += $result.Text
}
$engine.Dispose()
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output ($words -join ' ')
