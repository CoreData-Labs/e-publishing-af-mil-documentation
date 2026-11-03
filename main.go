package main // declare the main package so this builds as an executable program

import ( // start of the standard library import block
	"context"       // package for context management, request cancellation, and timeouts
	"crypto/sha256" // package for generating SHA-256 cryptographic check values
	"encoding/hex"  // package for converting binary byte hashes into readable strings
	"errors"        // package for inspecting and comparing standard error values
	"fmt"           // package for formatted input and output string operations
	"io"            // package for foundational sequential data stream interactions
	"log"           // package providing timestamped logging to standard output
	"log/slog"      // package providing structured key-value logging capabilities
	"net/http"      // package providing comprehensive HTTP client and server features
	"net/url"       // package for parsing, validating, and escaping web addresses
	"os"            // package for operating system interface and direct file operations
	"os/signal"     // package for trapping incoming operating system signals
	"path"          // package for manipulating standard forward-slash separated path segments
	"path/filepath" // package for handling native file system path syntax across platforms
	"regexp"        // package supporting pattern-based regular expression search operations
	"strings"       // package providing helper utilities for string searching and manipulation
	"syscall"       // package containing low-level operating system primitives and signal constants
	"time"          // package providing utilities for durations, clocks, and timeouts
) // end of the standard library import block

// publicationCatalog describes one catalog API that lists publications
type publicationCatalog struct { // holds the settings needed to query a single catalog
	catalogName                    string // human readable label used in log messages
	endpointUniformResourceLocator string // full API address that returns the catalog payload
	tabIdentifier                  string // value sent in the TabId header for this catalog
	moduleIdentifier               string // value sent in the ModuleId header for this catalog
} // end of publicationCatalog type

// publicationCatalogsInProcessingOrder lists every catalog; each one is fully downloaded before the next starts
var publicationCatalogsInProcessingOrder = []publicationCatalog{ // ordered slice so the first API always runs first
	{ // first catalog entry
		catalogName:                    "AirForceDepartmentalPublications",                                                                                 // label for the first API
		endpointUniformResourceLocator: "https://www.e-publishing.af.mil/DesktopModules/MVC/EPUBS/EPUB/GetPubsBySeriesView/?orgID=10141&catID=1&series=-1", // first API address
		tabIdentifier:                  "131",                                                                                                              // TabId header value for the first API
		moduleIdentifier:               "449",                                                                                                              // ModuleId header value for the first API
	}, // end of first catalog entry
	{ // second catalog entry
		catalogName:                    "AirNationalGuardAllPublications",                                                                                // label for the second API
		endpointUniformResourceLocator: "https://www.e-publishing.af.mil/DesktopModules/MVC/EPUBS/EPUB/GetPubsBySeriesView/?orgID=44&catID=16&series=-1", // second API address
		tabIdentifier:                  "131",                                                                                                            // TabId header value for the second API
		moduleIdentifier:               "449",                                                                                                            // ModuleId header value for the second API
	}, // end of second catalog entry
	{ // third catalog entry
		catalogName:                    "UnitedStatesSpaceForceCombatForcesCommandAllPublications",                                                       // label for the third API
		endpointUniformResourceLocator: "https://www.e-publishing.af.mil/DesktopModules/MVC/EPUBS/EPUB/GetPubsBySeriesView/?orgID=47&catID=20&series=-1", // third API address
		tabIdentifier:                  "131",                                                                                                            // TabId header value for the third API
		moduleIdentifier:               "449",                                                                                                            // ModuleId header value for the third API
	}, // end of third catalog entry
} // end of the catalog list

// portableDocumentFormatRegularExpression locates target PDF URLs inside raw catalog HTML
var portableDocumentFormatRegularExpression = regexp.MustCompile(`(?i)https?://[^"'\s<>\\]+\.pdf`) // compiled once during application startup

// invalidFilenameCharacterRunRegularExpression matches any run of one or more characters that are not 0-9 or a-z
var invalidFilenameCharacterRunRegularExpression = regexp.MustCompile(`[^a-z0-9]+`) // a whole run becomes one underscore, so "__" can never appear

// fallbackFilenameBase is used when sanitizing leaves nothing behind (for example a name made only of symbols)
const fallbackFilenameBase = "document" // safe default base name without extension

// portableDocumentFormatExtension is the extension appended to every sanitized file name
const portableDocumentFormatExtension = ".pdf" // lowercase extension, valid for every saved file

// sharedHypertextTransferProtocolClient provides pooled connections with an overall request timeout
var sharedHypertextTransferProtocolClient = &http.Client{ // configure globally accessible HTTP client
	Timeout: 180 * time.Second, // establish client-side network timeout ceiling
} // finish HTTP client configuration

// buildSafePortableDocumentFormatFilename converts any raw name into a valid PDF file name.
// Rules: only 0-9, a-z and _ are allowed, no leading or trailing _, and no repeated __.
func buildSafePortableDocumentFormatFilename(rawFilename string) string { // accepts any raw name, returns a clean name with .pdf
	filenameWithoutExtension := strings.TrimSuffix(rawFilename, portableDocumentFormatExtension)                 // drop a lowercase .pdf extension if present
	filenameWithoutExtension = strings.TrimSuffix(filenameWithoutExtension, ".PDF")                              // drop an uppercase .PDF extension if present
	lowercaseFilename := strings.ToLower(filenameWithoutExtension)                                               // lowercase everything because A-Z is not an allowed range
	underscoredFilename := invalidFilenameCharacterRunRegularExpression.ReplaceAllString(lowercaseFilename, "_") // replace every run of invalid characters (including existing underscores) with one underscore
	trimmedFilename := strings.Trim(underscoredFilename, "_")                                                    // remove any underscore at the start or the end
	if trimmedFilename == "" {                                                                                   // check whether nothing valid was left
		trimmedFilename = fallbackFilenameBase // use the fallback base name instead of an empty name
	} // end empty-name check
	return trimmedFilename + portableDocumentFormatExtension // attach the .pdf extension and return the final name
} // end of buildSafePortableDocumentFormatFilename function

// applyBrowserRequestHeaders applies all necessary headers to mimic an authorized desktop browser
func applyBrowserRequestHeaders(hypertextTransferProtocolRequest *http.Request) { // accepts pointer to target request
	hypertextTransferProtocolRequest.Header.Set("sec-ch-ua-platform", "\"Chrome OS\"")                                                                                          // indicate operating platform environment
	hypertextTransferProtocolRequest.Header.Set("Referer", "https://www.e-publishing.af.mil/Product-Index/")                                                                    // specify referring index page to satisfy cross-origin checks
	hypertextTransferProtocolRequest.Header.Set("sec-ch-ua", "\"Not-A.Brand\";v=\"99\", \"Google Chrome\";v=\"157\", \"Chromium\";v=\"157\"")                                   // report browser user agent brands
	hypertextTransferProtocolRequest.Header.Set("sec-ch-ua-mobile", "?0")                                                                                                       // indicate non-mobile platform architecture
	hypertextTransferProtocolRequest.Header.Set("X-Requested-With", "XMLHttpRequest")                                                                                           // indicate asynchronous AJAX transaction
	hypertextTransferProtocolRequest.Header.Set("User-Agent", "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36") // set modern Chrome browser identifier
	hypertextTransferProtocolRequest.Header.Set("Accept", "*/*")                                                                                                                // signal acceptance of any MIME content type
	hypertextTransferProtocolRequest.Header.Set("DNT", "1")                                                                                                                     // signal request not to track browsing
} // end of applyBrowserRequestHeaders function

// fetchPublicationCatalog queries one catalog endpoint and yields the response body as a string
func fetchPublicationCatalog(executionScopeContext context.Context, catalogToFetch publicationCatalog) (string, error) { // returns string body and error
	hypertextTransferProtocolRequest, requestConstructionError := http.NewRequestWithContext(executionScopeContext, http.MethodGet, catalogToFetch.endpointUniformResourceLocator, nil) // build request with context
	if requestConstructionError != nil {                                                                                                                                                // check whether request assembly failed
		return "", fmt.Errorf("failed to construct request for catalog %s: %w", catalogToFetch.catalogName, requestConstructionError) // return wrapped error description
	} // end request check

	applyBrowserRequestHeaders(hypertextTransferProtocolRequest)                             // attach browser headers to satisfy endpoint security
	hypertextTransferProtocolRequest.Header.Set("TabId", catalogToFetch.tabIdentifier)       // configure portal tab identifier for this catalog
	hypertextTransferProtocolRequest.Header.Set("ModuleId", catalogToFetch.moduleIdentifier) // configure target module identifier for this catalog

	slog.Info("Dispatching HTTP request to query the publication catalog", "catalog", catalogToFetch.catalogName, "endpoint", catalogToFetch.endpointUniformResourceLocator) // log catalog retrieval attempt

	hypertextTransferProtocolResponse, networkExchangeError := sharedHypertextTransferProtocolClient.Do(hypertextTransferProtocolRequest) // execute network operation
	if networkExchangeError != nil {                                                                                                      // check whether network round-trip failed
		return "", fmt.Errorf("failed to retrieve data for catalog %s: %w", catalogToFetch.catalogName, networkExchangeError) // return wrapped transport error
	} // end network error check
	defer hypertextTransferProtocolResponse.Body.Close() // guarantee deferred release of TCP network socket

	if hypertextTransferProtocolResponse.StatusCode != http.StatusOK { // verify receipt of standard HTTP 200 status
		return "", fmt.Errorf("catalog %s answered with unexpected HTTP status: %s", catalogToFetch.catalogName, hypertextTransferProtocolResponse.Status) // report non-200 status code
	} // end status verification

	responseByteData, payloadReadError := io.ReadAll(hypertextTransferProtocolResponse.Body) // slurp complete response stream
	if payloadReadError != nil {                                                             // verify successful stream completion
		return "", fmt.Errorf("failed to read body of catalog %s: %w", catalogToFetch.catalogName, payloadReadError) // report read failure
	} // end stream read check

	return string(responseByteData), nil // convert raw bytes into character sequence and return
} // end of fetchPublicationCatalog function

// removeDuplicatesFromSlice removes repeated strings from a slice while keeping the original order
func removeDuplicatesFromSlice(originalStrings []string) []string { // accepts a slice that may hold duplicates
	alreadySeenStrings := make(map[string]bool)              // map that remembers every string already kept
	uniqueStrings := make([]string, 0, len(originalStrings)) // preallocate the result slice with enough capacity
	for _, currentString := range originalStrings {          // walk every string in the original order
		if !alreadySeenStrings[currentString] { // check whether this string has not been kept yet
			alreadySeenStrings[currentString] = true             // mark this string as seen
			uniqueStrings = append(uniqueStrings, currentString) // keep the first occurrence
		} // end of the first-occurrence check
	} // end of the iteration over original strings
	return uniqueStrings // return the de-duplicated slice
} // end of removeDuplicatesFromSlice function

// extractPortableDocumentFormatUniformResourceLocators filters and deduplicates all PDF references
func extractPortableDocumentFormatUniformResourceLocators(rawPayloadContent string) []string { // accepts raw string and outputs slice
	allFoundUniformResourceLocators := portableDocumentFormatRegularExpression.FindAllString(rawPayloadContent, -1) // collect all matches via regex
	normalizedUniformResourceLocators := make([]string, 0, len(allFoundUniformResourceLocators))                    // preallocate slice for trimmed URLs

	for _, candidateUniformResourceLocator := range allFoundUniformResourceLocators { // walk every discovered address
		normalizedCandidate := strings.TrimSpace(candidateUniformResourceLocator)                          // remove surrounding white-space
		normalizedUniformResourceLocators = append(normalizedUniformResourceLocators, normalizedCandidate) // store normalized URL
	} // end iteration

	return removeDuplicatesFromSlice(normalizedUniformResourceLocators) // remove duplicates and return unique URLs
} // end of extractPortableDocumentFormatUniformResourceLocators function

// extractFilenameFromUniformResourceLocator isolates the final file token from an address
func extractFilenameFromUniformResourceLocator(targetUniformResourceLocator string) (string, error) { // returns base name and error
	parsedUniformResourceLocator, parseError := url.Parse(targetUniformResourceLocator) // parse input into URI structure
	if parseError != nil {                                                              // check for malformed URL components
		return "", fmt.Errorf("unable to parse URL segment: %w", parseError) // return parsing error
	} // end parse check

	return path.Base(parsedUniformResourceLocator.Path), nil // retrieve trailing path component
} // end of extractFilenameFromUniformResourceLocator function

// downloadPortableDocumentFormatFile downloads and saves a single document while generating a hash digest
func downloadPortableDocumentFormatFile(executionScopeContext context.Context, targetUniformResourceLocator string, targetDestinationDirectory string) (string, error) { // downloads and persists file
	rawFilename, filenameExtractionError := extractFilenameFromUniformResourceLocator(targetUniformResourceLocator) // extract the raw file name from the URL
	if filenameExtractionError != nil {                                                                             // verify valid file name
		return "", filenameExtractionError // return extraction error
	} // end error verification

	safeFilename := buildSafePortableDocumentFormatFilename(rawFilename) // convert the raw name into a valid name following the naming rules

	finalDestinationPath := filepath.Join(targetDestinationDirectory, safeFilename) // assemble full system target path

	if _, fileStatisticsError := os.Stat(finalDestinationPath); fileStatisticsError == nil { // check if file is already on disk
		return "skipped (file already exists)", nil // skip network download
	} else if !errors.Is(fileStatisticsError, os.ErrNotExist) { // check for unexpected filesystem permission or I/O errors
		return "", fmt.Errorf("unable to inspect target path %s: %w", finalDestinationPath, fileStatisticsError) // return stat error
	} // end file check

	hypertextTransferProtocolRequest, downloadRequestError := http.NewRequestWithContext(executionScopeContext, http.MethodGet, targetUniformResourceLocator, nil) // construct download request with context
	if downloadRequestError != nil {                                                                                                                               // check request creation status
		return "", fmt.Errorf("failed to create download request for %s: %w", targetUniformResourceLocator, downloadRequestError) // return construction failure
	} // end request creation check

	applyBrowserRequestHeaders(hypertextTransferProtocolRequest) // apply browser spoofing headers to avoid access denial

	downloadResponse, downloadExecutionError := sharedHypertextTransferProtocolClient.Do(hypertextTransferProtocolRequest) // perform file fetch
	if downloadExecutionError != nil {                                                                                     // verify network transaction status
		return "", fmt.Errorf("failed to download resource %s: %w", targetUniformResourceLocator, downloadExecutionError) // return transport error
	} // end execution error check
	defer downloadResponse.Body.Close() // schedule socket termination

	if downloadResponse.StatusCode != http.StatusOK { // verify valid server response
		return "", fmt.Errorf("server responded with status %s for url: %s", downloadResponse.Status, targetUniformResourceLocator) // return failure response code
	} // end HTTP status check

	temporaryFilePath := finalDestinationPath + ".part"                    // construct path for incomplete payload
	temporaryFileHandle, fileCreationError := os.Create(temporaryFilePath) // open temporary disk file
	if fileCreationError != nil {                                          // inspect file creation status
		return "", fmt.Errorf("failed to initialize temporary file %s: %w", temporaryFilePath, fileCreationError) // return file error
	} // end file creation check

	secureHashAlgorithmInstance := sha256.New()                                                // instantiate SHA-256 state tracker
	multiWriterDestination := io.MultiWriter(temporaryFileHandle, secureHashAlgorithmInstance) // write to disk and compute hash simultaneously
	_, streamCopyError := io.Copy(multiWriterDestination, downloadResponse.Body)               // stream response content through multi-writer
	fileCloseError := temporaryFileHandle.Close()                                              // flush buffer and close file descriptor

	if streamCopyError != nil { // verify copy status
		_ = os.Remove(temporaryFilePath)                                                       // remove partial file on error
		return "", fmt.Errorf("interrupted while copying stream to disk: %w", streamCopyError) // return stream failure
	} // end copy verification

	if fileCloseError != nil { // verify clean handle closure
		_ = os.Remove(temporaryFilePath)                                                                // remove incomplete artifact
		return "", fmt.Errorf("failed to cleanly close file %s: %w", temporaryFilePath, fileCloseError) // return close error
	} // end file close check

	if fileRenameError := os.Rename(temporaryFilePath, finalDestinationPath); fileRenameError != nil { // atomically move file to target destination
		return "", fmt.Errorf("failed to finalize temporary file name: %w", fileRenameError) // return rename error
	} // end rename check

	hexadecimalDigestRepresentation := hex.EncodeToString(secureHashAlgorithmInstance.Sum(nil))      // convert cryptographic hash to hex string
	return fmt.Sprintf("downloaded successfully [SHA256: %s]", hexadecimalDigestRepresentation), nil // return formatted success summary
} // end of downloadPortableDocumentFormatFile function

// downloadAllPortableDocumentFormatFiles sequentially downloads all discovered PDF files
func downloadAllPortableDocumentFormatFiles(executionScopeContext context.Context, uniformResourceLocators []string, targetDestinationDirectory string) { // executes sequential downloads
	if directoryCreationError := os.MkdirAll(targetDestinationDirectory, 0o755); directoryCreationError != nil { // create destination directory
		log.Fatalf("Fatal error: Failed to create target output directory %s: %v", targetDestinationDirectory, directoryCreationError) // terminate on disk error
	} // end directory verification

	slog.Info("Starting sequential download process", "directory", targetDestinationDirectory, "total_files", len(uniformResourceLocators)) // report start of downloads

	for index, currentTargetUniformResourceLocator := range uniformResourceLocators { // iterate over every discovered URL sequentially
		if executionScopeContext.Err() != nil { // check if OS interrupt signal cancelled the context
			slog.Warn("Download loop aborted due to context cancellation", "reason", executionScopeContext.Err()) // log cancellation event
			break                                                                                                 // exit loop cleanly
		} // end cancellation check

		downloadResultStatus, downloadEncounteredError := downloadPortableDocumentFormatFile(executionScopeContext, currentTargetUniformResourceLocator, targetDestinationDirectory) // execute download
		if downloadEncounteredError != nil {                                                                                                                                         // check if error occurred
			slog.Error("File download failed", "index", index+1, "url", currentTargetUniformResourceLocator, "error", downloadEncounteredError) // log structured error
		} else { // download finished without issues
			slog.Info("File processed", "index", index+1, "status", downloadResultStatus, "url", currentTargetUniformResourceLocator) // log structured status
		} // end status check
	} // end URL iteration loop

	slog.Info("Batch download process finished") // log batch completion
} // end of downloadAllPortableDocumentFormatFiles function

func main() { // application execution entrypoint
	targetDestinationDirectory := "PDFs" // define default local filesystem directory where files are saved

	log.SetFlags(log.Ldate | log.Ltime | log.Lshortfile | log.Lmsgprefix) // configure standard logger with date, time, file line, and prefix
	log.SetPrefix("[AirForce-Downloader] ")                               // configure prefix label on every log entry

	structuredLogger := slog.New(slog.NewTextHandler(os.Stdout, nil)) // create structured text logger writing to standard output
	slog.SetDefault(structuredLogger)                                 // register structured logger as global default

	applicationScopeContext, stopSignalListener := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM) // build root context listening for Ctrl+C and termination signals
	defer stopSignalListener()                                                                                               // guarantee signal listener cleanup on program exit

	slog.Info("Initializing Air Force publication harvesting process") // log application start

	for catalogIndex, currentCatalog := range publicationCatalogsInProcessingOrder { // process each catalog in order, one at a time
		if applicationScopeContext.Err() != nil { // check if an interrupt arrived before starting the next catalog
			slog.Warn("Catalog processing aborted due to context cancellation", "reason", applicationScopeContext.Err()) // log cancellation event
			break                                                                                                        // stop processing remaining catalogs
		} // end cancellation check

		slog.Info("Starting catalog", "position", catalogIndex+1, "total_catalogs", len(publicationCatalogsInProcessingOrder), "catalog", currentCatalog.catalogName) // log which catalog is starting

		publicationIndexPayload, catalogFetchError := fetchPublicationCatalog(applicationScopeContext, currentCatalog) // retrieve catalog data for this API
		if catalogFetchError != nil {                                                                                  // check if index fetch failed
			slog.Error("Catalog fetch failed, moving to the next catalog", "catalog", currentCatalog.catalogName, "error", catalogFetchError) // log the failure without stopping the program
			continue                                                                                                                          // skip to the next catalog
		} // end error check

		discoveredUniformResourceLocators := extractPortableDocumentFormatUniformResourceLocators(publicationIndexPayload)                               // parse out target links
		slog.Info("Discovered unique PDF publication endpoints", "catalog", currentCatalog.catalogName, "count", len(discoveredUniformResourceLocators)) // print link count

		downloadAllPortableDocumentFormatFiles(applicationScopeContext, discoveredUniformResourceLocators, targetDestinationDirectory) // download everything from this catalog before the loop moves on

		slog.Info("Finished catalog", "catalog", currentCatalog.catalogName) // log that this catalog is fully done
	} // end of catalog loop

	slog.Info("All catalogs processed") // log completion of the whole run
} // end of main function
