$baseUrl = "http://127.0.0.1:8001"

Write-Host "Testing Nurse Dashboard Lokasi Filtering..."

# Get login page and CSRF token
try {
    $loginPage = Invoke-WebRequest -Uri "$baseUrl/accounts/login/" -SessionVariable session
    $csrfToken = ($loginPage.Content | Select-String 'name="csrfmiddlewaretoken" value="([^"]+)"').Matches[0].Groups[1].Value
    Write-Host "CSRF Token obtained: $($csrfToken.Substring(0,10))..."
} catch {
    Write-Host "Error getting login page: $($_.Exception.Message)"
    exit 1
}

# Login as nurse
try {
    $loginData = @{
        'csrfmiddlewaretoken' = $csrfToken
        'username' = 'nurse'
        'password' = 'nurse123'
    }
    $loginResponse = Invoke-WebRequest -Uri "$baseUrl/accounts/login/" -Method POST -Body $loginData -WebSession $session
    Write-Host "Login Status: $($loginResponse.StatusCode)"
} catch {
    Write-Host "Error during login: $($_.Exception.Message)"
    exit 1
}

# Test nurse well_unwell_summary_json endpoint with different lokasi values
$testCases = @(
    @{ lokasi = ""; description = "no lokasi parameter" },
    @{ lokasi = "all"; description = "lokasi=all" },
    @{ lokasi = "ab-100"; description = "lokasi=ab-100" },
    @{ lokasi = "ehr#10"; description = "lokasi=ehr#10" }
)

foreach ($testCase in $testCases) {
    Write-Host "`n--- Testing $($testCase.description) ---"
    
    $url = "$baseUrl/nurse/well-unwell-summary-json/?month_from=2024-01&month_to=2024-12"
    if ($testCase.lokasi -ne "") {
        $url += "&lokasi=$($testCase.lokasi)"
    }
    
    Write-Host "URL: $url"
    
    try {
        $response = Invoke-WebRequest -Uri $url -WebSession $session
        Write-Host "Status: $($response.StatusCode)"
        $jsonResponse = $response.Content | ConvertFrom-Json
        Write-Host "Data points: $($jsonResponse.Count)"
        if ($jsonResponse.Count -gt 0) {
            Write-Host "Sample: $($jsonResponse[0] | ConvertTo-Json -Compress)"
        }
    } catch {
        Write-Host "Error: $($_.Exception.Message)"
    }
}

Write-Host "`nNurse lokasi filtering test completed."