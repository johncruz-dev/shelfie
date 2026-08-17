import { StatusBar } from 'expo-status-bar';
import * as ImagePicker from 'expo-image-picker';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

const API_URL = (process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

const colors = {
  ink: '#252A24',
  forest: '#234D3C',
  cream: '#F6F1E7',
  paper: '#FFFCF6',
  sage: '#DDE8DA',
  amber: '#E9B44C',
  red: '#A3483F',
  muted: '#6D736B',
  border: '#DDD8CD',
};

function confidenceBand(value) {
  if (value == null) return 'unmatched';
  if (value >= 0.82) return 'high';
  if (value >= 0.45) return 'low';
  return 'unmatched';
}

function confidenceLabel(value) {
  if (value == null) return 'No match';
  return `${Math.round(value * 100)}% match`;
}

function imageFile(asset) {
  const extension = asset.fileName?.split('.').pop()?.toLowerCase() || 'jpg';
  const type = asset.mimeType || (extension === 'png' ? 'image/png' : 'image/jpeg');
  return {
    uri: asset.uri,
    name: asset.fileName || `shelf.${extension}`,
    type,
  };
}

function needsReview(item) {
  return item.review_status === 'pending';
}

function displayTitle(item) {
  return item.corrected_title || item.matched_book?.title || item.raw_title || 'Unreadable spine';
}

function displayAuthor(item) {
  return (
    item.corrected_author ||
    item.matched_book?.author ||
    item.raw_author ||
    item.ocr_error ||
    'Unknown author'
  );
}

async function apiJson(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(options.body && !(options.body instanceof FormData)
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Request failed (${response.status})`);
  }
  return payload;
}

export default function App() {
  const [tab, setTab] = useState('scan');
  const [photo, setPhoto] = useState(null);
  const [scan, setScan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [library, setLibrary] = useState([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [editDrafts, setEditDrafts] = useState({});

  const detections = scan?.detections || [];
  const summary = scan?.summary;
  const pending = useMemo(() => detections.filter(needsReview), [detections]);
  const ready = useMemo(
    () => detections.filter((item) => item.review_status === 'auto_accepted'),
    [detections],
  );

  const loadLibrary = useCallback(async () => {
    setLibraryLoading(true);
    try {
      const data = await apiJson('/api/library/');
      setLibrary(Array.isArray(data) ? data : data.results || []);
    } catch (err) {
      // Keep previous list; surface quietly on library tab.
      setError(err.message);
    } finally {
      setLibraryLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'library') loadLibrary();
  }, [tab, loadLibrary]);

  async function pickFromLibrary() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Photo access needed', 'Allow photo access to choose a bookshelf image.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.9,
    });
    if (!result.canceled) selectPhoto(result.assets[0]);
  }

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Camera access needed', 'Allow camera access to photograph your bookshelf.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ['images'],
      quality: 0.9,
    });
    if (!result.canceled) selectPhoto(result.assets[0]);
  }

  function selectPhoto(asset) {
    setPhoto(asset);
    setScan(null);
    setError('');
    setEditDrafts({});
    setTab('scan');
  }

  async function scanShelf() {
    if (!photo || loading) return;
    setLoading(true);
    setError('');
    setScan(null);

    try {
      const body = new FormData();
      body.append('image', imageFile(photo));
      const payload = await apiJson('/api/scans/', { method: 'POST', body });
      setScan(payload);
      const drafts = {};
      (payload.detections || []).forEach((item) => {
        drafts[item.id] = {
          title: item.matched_book?.title || item.raw_title || '',
          author: item.matched_book?.author || item.raw_author || '',
        };
      });
      setEditDrafts(drafts);
      if ((payload.detections || []).some(needsReview)) {
        setTab('review');
      }
    } catch (requestError) {
      const hint =
        Platform.OS === 'android' && API_URL.includes('localhost')
          ? ' On a phone, set EXPO_PUBLIC_API_URL to your computer’s LAN IP.'
          : '';
      setError(`${requestError.message || 'Could not scan this photo.'}${hint}`);
    } finally {
      setLoading(false);
    }
  }

  function updateDetectionInScan(updated) {
    setScan((prev) => {
      if (!prev) return prev;
      return {
        ...prev,
        detections: (prev.detections || []).map((item) =>
          item.id === updated.id ? { ...item, ...updated } : item,
        ),
      };
    });
  }

  async function acceptItem(item) {
    setBusyId(item.id);
    setError('');
    try {
      const payload = await apiJson(`/api/detections/${item.id}/accept/`, {
        method: 'POST',
        body: JSON.stringify({ add_to_library: true }),
      });
      updateDetectionInScan(payload.detection);
      await loadLibrary();
    } catch (err) {
      Alert.alert('Could not accept', err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function discardItem(item) {
    setBusyId(item.id);
    setError('');
    try {
      const payload = await apiJson(`/api/detections/${item.id}/discard/`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      updateDetectionInScan(payload.detection);
    } catch (err) {
      Alert.alert('Could not discard', err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function saveCorrection(item) {
    const draft = editDrafts[item.id] || { title: '', author: '' };
    if (!draft.title.trim()) {
      Alert.alert('Title required', 'Enter a title before saving this correction.');
      return;
    }
    setBusyId(item.id);
    setError('');
    try {
      const payload = await apiJson(`/api/detections/${item.id}/correct/`, {
        method: 'POST',
        body: JSON.stringify({
          title: draft.title.trim(),
          author: (draft.author || '').trim(),
          add_to_library: true,
        }),
      });
      updateDetectionInScan(payload.detection);
      await loadLibrary();
    } catch (err) {
      Alert.alert('Could not save', err.message);
    } finally {
      setBusyId(null);
    }
  }

  async function acceptAllReady() {
    if (!scan?.id || !ready.length) return;
    setBusyId('bulk');
    try {
      await apiJson(`/api/scans/${scan.id}/accept-high-confidence/`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      // Refresh scan details so review_status updates.
      const refreshed = await apiJson(`/api/scans/${scan.id}/`);
      setScan(refreshed);
      await loadLibrary();
      Alert.alert('Added to library', `${ready.length} high-confidence book(s) saved.`);
    } catch (err) {
      Alert.alert('Bulk accept failed', err.message);
    } finally {
      setBusyId(null);
    }
  }

  function reset() {
    setPhoto(null);
    setScan(null);
    setError('');
    setEditDrafts({});
    setTab('scan');
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <View style={styles.header}>
        <View>
          <Text style={styles.brand}>SHELFIE</Text>
          <Text style={styles.title}>
            {tab === 'scan' ? 'Shelf to library.' : tab === 'review' ? 'Review matches.' : 'Your library.'}
          </Text>
        </View>
        <View style={styles.localBadge}>
          <View style={styles.localDot} />
          <Text style={styles.localText}>
            {tab === 'library' ? `${library.length} books` : 'Local detect'}
          </Text>
        </View>
      </View>

      <View style={styles.tabs}>
        {[
          { id: 'scan', label: 'Scan' },
          { id: 'review', label: pending.length ? `Review (${pending.length})` : 'Review' },
          { id: 'library', label: 'Library' },
        ].map((item) => (
          <Pressable
            key={item.id}
            style={[styles.tab, tab === item.id && styles.tabActive]}
            onPress={() => setTab(item.id)}
          >
            <Text style={[styles.tabText, tab === item.id && styles.tabTextActive]}>{item.label}</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView contentContainerStyle={styles.page}>
        {tab === 'scan' && (
          <>
            {!photo ? (
              <View style={styles.heroCard}>
                <View style={styles.bookIcon}>
                  <View style={[styles.book, styles.bookOne]} />
                  <View style={[styles.book, styles.bookTwo]} />
                  <View style={[styles.book, styles.bookThree]} />
                </View>
                <Text style={styles.heroTitle}>Scan your bookshelf</Text>
                <Text style={styles.heroBody}>
                  Take one clear, straight-on photo. Low-confidence matches go to Review — never
                  silently accepted or dropped.
                </Text>
                <Pressable style={styles.primaryButton} onPress={takePhoto}>
                  <Text style={styles.primaryButtonText}>Take a photo</Text>
                </Pressable>
                <Pressable style={styles.secondaryButton} onPress={pickFromLibrary}>
                  <Text style={styles.secondaryButtonText}>Choose from library</Text>
                </Pressable>
                <Text style={styles.privacy}>Spine detection runs locally. Only crops go to Gemini.</Text>
              </View>
            ) : (
              <>
                <View style={styles.photoCard}>
                  <Image source={{ uri: photo.uri }} style={styles.preview} resizeMode="cover" />
                  {!loading && !scan && (
                    <Pressable style={styles.changeButton} onPress={pickFromLibrary}>
                      <Text style={styles.changeButtonText}>Change photo</Text>
                    </Pressable>
                  )}
                  {loading && (
                    <View style={styles.loadingOverlay}>
                      <ActivityIndicator size="large" color="#F8F4EA" />
                      <Text style={styles.loadingTitle}>Reading your shelf…</Text>
                      <Text style={styles.loadingText}>
                        Finding spines → reading text → matching catalog
                      </Text>
                    </View>
                  )}
                </View>

                {!loading && !scan && (
                  <Pressable style={styles.primaryButton} onPress={scanShelf}>
                    <Text style={styles.primaryButtonText}>Scan this shelf</Text>
                  </Pressable>
                )}

                {!!error && tab === 'scan' && (
                  <View style={styles.errorCard}>
                    <Text style={styles.errorTitle}>We couldn’t process that photo</Text>
                    <Text style={styles.errorBody}>{error}</Text>
                    <Pressable style={styles.errorAction} onPress={scanShelf}>
                      <Text style={styles.errorActionText}>Try again</Text>
                    </Pressable>
                  </View>
                )}

                {!!scan && (
                  <>
                    <View style={styles.summaryCard}>
                      <View>
                        <Text style={styles.summaryTitle}>
                          {detections.length ? `${detections.length} spines found` : 'No books found'}
                        </Text>
                        <Text style={styles.summaryBody}>
                          {summary?.message ||
                            `${ready.length} ready · ${pending.length} need review`}
                        </Text>
                      </View>
                      <View style={styles.metric}>
                        <Text style={styles.metricValue}>
                          {scan.latency_ms == null ? '—' : `${(scan.latency_ms / 1000).toFixed(1)}s`}
                        </Text>
                        <Text style={styles.metricLabel}>latency</Text>
                      </View>
                    </View>

                    {detections.map((item, index) => {
                      const band = confidenceBand(item.match_confidence);
                      return (
                        <View key={item.id || index} style={styles.resultCard}>
                          {item.crop_image ? (
                            <Image source={{ uri: item.crop_image }} style={styles.crop} />
                          ) : (
                            <View style={styles.cropFallback}>
                              <Text style={styles.cropFallbackText}>{index + 1}</Text>
                            </View>
                          )}
                          <View style={styles.resultText}>
                            <Text numberOfLines={2} style={styles.bookTitle}>
                              {displayTitle(item)}
                            </Text>
                            <Text numberOfLines={1} style={styles.author}>
                              {displayAuthor(item)}
                            </Text>
                            <View style={[styles.confidence, styles[`confidence_${band}`]]}>
                              <Text style={[styles.confidenceText, styles[`confidenceText_${band}`]]}>
                                {item.review_status === 'pending' ? 'Review · ' : 'Ready · '}
                                {confidenceLabel(item.match_confidence)}
                              </Text>
                            </View>
                          </View>
                        </View>
                      );
                    })}

                    {pending.length > 0 && (
                      <Pressable style={styles.primaryButton} onPress={() => setTab('review')}>
                        <Text style={styles.primaryButtonText}>
                          Review {pending.length} uncertain {pending.length === 1 ? 'book' : 'books'}
                        </Text>
                      </Pressable>
                    )}
                    {ready.length > 0 && (
                      <Pressable
                        style={styles.secondaryButton}
                        onPress={acceptAllReady}
                        disabled={busyId === 'bulk'}
                      >
                        <Text style={styles.secondaryButtonText}>
                          {busyId === 'bulk' ? 'Adding…' : `Add ${ready.length} ready to library`}
                        </Text>
                      </Pressable>
                    )}
                    <Pressable style={styles.secondaryButton} onPress={reset}>
                      <Text style={styles.secondaryButtonText}>Scan another shelf</Text>
                    </Pressable>
                  </>
                )}
              </>
            )}
          </>
        )}

        {tab === 'review' && (
          <>
            {!scan ? (
              <View style={styles.emptyCard}>
                <Text style={styles.emptyTitle}>Nothing to review yet</Text>
                <Text style={styles.emptyBody}>
                  Scan a shelf first. Low-confidence and unmatched spines will land here for you to
                  confirm, correct, or discard.
                </Text>
                <Pressable style={styles.primaryButton} onPress={() => setTab('scan')}>
                  <Text style={styles.primaryButtonText}>Go to Scan</Text>
                </Pressable>
              </View>
            ) : pending.length === 0 ? (
              <View style={styles.emptyCard}>
                <Text style={styles.emptyTitle}>Review complete</Text>
                <Text style={styles.emptyBody}>
                  Every uncertain spine was confirmed or discarded. High-confidence matches can still
                  be added from Scan.
                </Text>
                <Pressable style={styles.primaryButton} onPress={() => setTab('library')}>
                  <Text style={styles.primaryButtonText}>Open library</Text>
                </Pressable>
              </View>
            ) : (
              <>
                <Text style={styles.sectionHint}>
                  These were not auto-accepted. Confirm the match, edit the title/author, or discard.
                </Text>
                {pending.map((item) => {
                  const draft = editDrafts[item.id] || { title: '', author: '' };
                  const candidates = item.match_candidates_json || [];
                  const busy = busyId === item.id;
                  return (
                    <View key={item.id} style={styles.reviewCard}>
                      <View style={styles.reviewTop}>
                        {item.crop_image ? (
                          <Image source={{ uri: item.crop_image }} style={styles.crop} />
                        ) : (
                          <View style={styles.cropFallback}>
                            <Text style={styles.cropFallbackText}>{item.spine_index + 1}</Text>
                          </View>
                        )}
                        <View style={{ flex: 1 }}>
                          <Text style={styles.reviewLabel}>OCR read</Text>
                          <Text style={styles.bookTitle}>
                            {item.raw_title || '(blank)'}
                            {item.raw_author ? ` — ${item.raw_author}` : ''}
                          </Text>
                          <Text style={styles.author}>
                            {confidenceLabel(item.match_confidence)}
                            {item.ocr_error ? ` · ${item.ocr_error}` : ''}
                          </Text>
                        </View>
                      </View>

                      <Text style={styles.fieldLabel}>Title</Text>
                      <TextInput
                        style={styles.input}
                        value={draft.title}
                        onChangeText={(text) =>
                          setEditDrafts((prev) => ({
                            ...prev,
                            [item.id]: { ...draft, title: text },
                          }))
                        }
                        placeholder="Book title"
                        placeholderTextColor={colors.muted}
                      />
                      <Text style={styles.fieldLabel}>Author</Text>
                      <TextInput
                        style={styles.input}
                        value={draft.author}
                        onChangeText={(text) =>
                          setEditDrafts((prev) => ({
                            ...prev,
                            [item.id]: { ...draft, author: text },
                          }))
                        }
                        placeholder="Author"
                        placeholderTextColor={colors.muted}
                      />

                      {candidates.length > 0 && (
                        <View style={styles.candidateBlock}>
                          <Text style={styles.fieldLabel}>Catalog suggestions</Text>
                          {candidates.slice(0, 3).map((cand) => (
                            <Pressable
                              key={cand.catalog_id}
                              style={styles.candidate}
                              onPress={() =>
                                setEditDrafts((prev) => ({
                                  ...prev,
                                  [item.id]: {
                                    title: cand.title,
                                    author: cand.author,
                                  },
                                }))
                              }
                            >
                              <Text style={styles.candidateTitle}>{cand.title}</Text>
                              <Text style={styles.candidateMeta}>
                                {cand.author} · {Math.round((cand.confidence || 0) * 100)}%
                              </Text>
                            </Pressable>
                          ))}
                        </View>
                      )}

                      <View style={styles.reviewActions}>
                        <Pressable
                          style={[styles.actionBtn, styles.actionAccept]}
                          disabled={busy}
                          onPress={() => acceptItem(item)}
                        >
                          <Text style={styles.actionAcceptText}>{busy ? '…' : 'Accept'}</Text>
                        </Pressable>
                        <Pressable
                          style={[styles.actionBtn, styles.actionSave]}
                          disabled={busy}
                          onPress={() => saveCorrection(item)}
                        >
                          <Text style={styles.actionSaveText}>{busy ? '…' : 'Save edit'}</Text>
                        </Pressable>
                        <Pressable
                          style={[styles.actionBtn, styles.actionDiscard]}
                          disabled={busy}
                          onPress={() => discardItem(item)}
                        >
                          <Text style={styles.actionDiscardText}>Discard</Text>
                        </Pressable>
                      </View>
                    </View>
                  );
                })}
              </>
            )}
          </>
        )}

        {tab === 'library' && (
          <>
            {libraryLoading && !library.length ? (
              <ActivityIndicator color={colors.forest} style={{ marginTop: 40 }} />
            ) : library.length === 0 ? (
              <View style={styles.emptyCard}>
                <Text style={styles.emptyTitle}>Library is empty</Text>
                <Text style={styles.emptyBody}>
                  Accepted and corrected books from a scan show up here as your personal shelf.
                </Text>
                <Pressable style={styles.primaryButton} onPress={() => setTab('scan')}>
                  <Text style={styles.primaryButtonText}>Scan a shelf</Text>
                </Pressable>
              </View>
            ) : (
              <>
                <Text style={styles.sectionHint}>{library.length} confirmed books</Text>
                {library.map((item) => (
                  <View key={item.id} style={styles.libraryCard}>
                    <Text style={styles.bookTitle}>{item.title}</Text>
                    <Text style={styles.author}>{item.author || 'Unknown author'}</Text>
                    {item.catalog_book?.catalog_id ? (
                      <Text style={styles.catalogId}>{item.catalog_book.catalog_id}</Text>
                    ) : null}
                  </View>
                ))}
                <Pressable style={styles.secondaryButton} onPress={loadLibrary}>
                  <Text style={styles.secondaryButtonText}>Refresh</Text>
                </Pressable>
              </>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  page: { flexGrow: 1, padding: 20, paddingBottom: 44, gap: 16 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
    marginHorizontal: 20,
    marginBottom: 6,
  },
  brand: { color: colors.forest, fontSize: 12, fontWeight: '900', letterSpacing: 2.4 },
  title: { color: colors.ink, fontSize: 26, fontWeight: '800', marginTop: 2 },
  localBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 18,
    backgroundColor: colors.sage,
  },
  localDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.forest },
  localText: { color: colors.forest, fontSize: 11, fontWeight: '700' },
  tabs: {
    flexDirection: 'row',
    marginHorizontal: 20,
    marginBottom: 4,
    backgroundColor: colors.paper,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 4,
    gap: 4,
  },
  tab: { flex: 1, paddingVertical: 10, borderRadius: 10, alignItems: 'center' },
  tabActive: { backgroundColor: colors.forest },
  tabText: { color: colors.muted, fontWeight: '800', fontSize: 13 },
  tabTextActive: { color: '#fff' },
  heroCard: {
    flex: 1,
    minHeight: 480,
    backgroundColor: colors.paper,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 26,
    justifyContent: 'center',
    alignItems: 'center',
  },
  bookIcon: { height: 116, width: 150, flexDirection: 'row', alignItems: 'flex-end', marginBottom: 30 },
  book: { borderRadius: 4, borderWidth: 3, borderColor: colors.ink, marginHorizontal: 3 },
  bookOne: { width: 36, height: 102, backgroundColor: colors.amber, transform: [{ rotate: '-5deg' }] },
  bookTwo: { width: 39, height: 112, backgroundColor: colors.forest },
  bookThree: { width: 42, height: 90, backgroundColor: '#C96D55', transform: [{ rotate: '5deg' }] },
  heroTitle: { color: colors.ink, fontSize: 26, fontWeight: '800', textAlign: 'center' },
  heroBody: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
    textAlign: 'center',
    marginTop: 10,
    marginBottom: 28,
  },
  primaryButton: {
    width: '100%',
    backgroundColor: colors.forest,
    paddingVertical: 16,
    borderRadius: 16,
    alignItems: 'center',
  },
  primaryButtonText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
  secondaryButton: {
    width: '100%',
    backgroundColor: 'transparent',
    paddingVertical: 15,
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: colors.forest,
    alignItems: 'center',
    marginTop: 11,
  },
  secondaryButtonText: { color: colors.forest, fontSize: 15, fontWeight: '800' },
  privacy: { color: colors.muted, fontSize: 11, textAlign: 'center', marginTop: 20 },
  photoCard: {
    position: 'relative',
    overflow: 'hidden',
    borderRadius: 22,
    backgroundColor: colors.ink,
    minHeight: 260,
  },
  preview: { width: '100%', height: 300 },
  changeButton: {
    position: 'absolute',
    right: 12,
    bottom: 12,
    backgroundColor: 'rgba(255,252,246,0.94)',
    paddingVertical: 9,
    paddingHorizontal: 13,
    borderRadius: 12,
  },
  changeButtonText: { color: colors.ink, fontWeight: '800', fontSize: 12 },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(24,48,38,0.86)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 28,
  },
  loadingTitle: { color: colors.paper, fontSize: 21, fontWeight: '800', marginTop: 16 },
  loadingText: { color: '#D8E2D8', fontSize: 12, textAlign: 'center', marginTop: 7 },
  errorCard: {
    borderRadius: 18,
    padding: 18,
    backgroundColor: '#F7E2DE',
    borderWidth: 1,
    borderColor: '#E7B9B2',
  },
  errorTitle: { color: colors.red, fontWeight: '800', fontSize: 16 },
  errorBody: { color: '#763D37', marginTop: 6, lineHeight: 20 },
  errorAction: { alignSelf: 'flex-start', marginTop: 12 },
  errorActionText: { color: colors.red, fontWeight: '900' },
  summaryCard: {
    backgroundColor: colors.forest,
    borderRadius: 20,
    padding: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  summaryTitle: { color: '#FFFFFF', fontSize: 18, fontWeight: '800' },
  summaryBody: { color: '#CFE0D8', marginTop: 4, maxWidth: 250 },
  metric: { alignItems: 'flex-end' },
  metricValue: { color: colors.amber, fontSize: 18, fontWeight: '900' },
  metricLabel: { color: '#CFE0D8', fontSize: 10, marginTop: 1 },
  resultCard: {
    flexDirection: 'row',
    backgroundColor: colors.paper,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    gap: 14,
    alignItems: 'center',
  },
  crop: { width: 48, height: 92, borderRadius: 8, backgroundColor: colors.sage },
  cropFallback: {
    width: 48,
    height: 92,
    borderRadius: 8,
    backgroundColor: colors.sage,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cropFallbackText: { color: colors.forest, fontWeight: '900', fontSize: 18 },
  resultText: { flex: 1 },
  bookTitle: { color: colors.ink, fontSize: 16, lineHeight: 20, fontWeight: '800' },
  author: { color: colors.muted, fontSize: 13, marginTop: 5 },
  confidence: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    paddingHorizontal: 9,
    paddingVertical: 5,
    marginTop: 10,
  },
  confidence_high: { backgroundColor: colors.sage },
  confidence_low: { backgroundColor: '#F8E8C5' },
  confidence_unmatched: { backgroundColor: '#F2DEDA' },
  confidenceText: { fontSize: 11, fontWeight: '800' },
  confidenceText_high: { color: colors.forest },
  confidenceText_low: { color: '#805C18' },
  confidenceText_unmatched: { color: colors.red },
  emptyCard: {
    backgroundColor: colors.paper,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 24,
    gap: 12,
  },
  emptyTitle: { color: colors.ink, fontSize: 20, fontWeight: '800' },
  emptyBody: { color: colors.muted, lineHeight: 21, marginBottom: 8 },
  sectionHint: { color: colors.muted, fontSize: 13, lineHeight: 18 },
  reviewCard: {
    backgroundColor: colors.paper,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 14,
    gap: 8,
  },
  reviewTop: { flexDirection: 'row', gap: 12, marginBottom: 6 },
  reviewLabel: { color: colors.muted, fontSize: 11, fontWeight: '700', marginBottom: 4 },
  fieldLabel: { color: colors.ink, fontSize: 12, fontWeight: '800', marginTop: 4 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.ink,
    backgroundColor: '#FFFEFA',
  },
  candidateBlock: { marginTop: 6, gap: 6 },
  candidate: {
    borderWidth: 1,
    borderColor: colors.sage,
    backgroundColor: '#F3F8F1',
    borderRadius: 12,
    padding: 10,
  },
  candidateTitle: { color: colors.ink, fontWeight: '800', fontSize: 13 },
  candidateMeta: { color: colors.muted, fontSize: 12, marginTop: 2 },
  reviewActions: { flexDirection: 'row', gap: 8, marginTop: 10 },
  actionBtn: { flex: 1, paddingVertical: 12, borderRadius: 12, alignItems: 'center' },
  actionAccept: { backgroundColor: colors.forest },
  actionAcceptText: { color: '#fff', fontWeight: '800' },
  actionSave: { backgroundColor: colors.amber },
  actionSaveText: { color: colors.ink, fontWeight: '800' },
  actionDiscard: { backgroundColor: '#F2DEDA' },
  actionDiscardText: { color: colors.red, fontWeight: '800' },
  libraryCard: {
    backgroundColor: colors.paper,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
  },
  catalogId: { color: colors.forest, fontSize: 11, fontWeight: '700', marginTop: 8 },
});
