import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import SurveyObservationsChart from './SurveyObservationsChart.jsx';
import i18n from '../i18n/index.js';
import { LabelProjectProvider } from '../i18n/LabelProjectContext.jsx';
import { resetTranslatedLabelsCache } from '../i18n/useTranslatedLabels.js';
import { translateLabels } from '../api/i18nApi.js';

vi.mock('../api/i18nApi.js', () => ({ translateLabels: vi.fn() }));

const OBSERVATIONS = [
  { study_key: 's1', question: 'Do you trust the news?', population: 'Adults', sample_size: 1000, cohort_dimension: 'age_group', cohort_value: 'young_adults', answer: 'Yes', percentage: 40 },
  { study_key: 's1', question: 'Do you trust the news?', population: 'Adults', sample_size: 1000, cohort_dimension: null, cohort_value: null, answer: 'No', percentage: 60 },
];

function renderSurvey(observations = OBSERVATIONS) {
  return render(<LabelProjectProvider value={2}><SurveyObservationsChart observations={observations} /></LabelProjectProvider>);
}

describe('SurveyObservationsChart', () => {
  beforeEach(() => {
    resetTranslatedLabelsCache();
    translateLabels.mockReset();
  });

  afterEach(async () => {
    await i18n.changeLanguage('en');
  });

  it('translates the question, population, cohort and answers in Arabic', async () => {
    await i18n.changeLanguage('ar');
    translateLabels.mockResolvedValue({
      'Do you trust the news?': 'هل تثق بالأخبار؟',
      Adults: 'البالغون',
      age_group: 'الفئة العمرية',
      young_adults: 'الشباب',
      Yes: 'نعم',
      No: 'لا',
    });
    renderSurvey();
    expect(await screen.findByText('هل تثق بالأخبار؟')).toBeInTheDocument();
    expect(screen.getByText(/البالغون/)).toBeInTheDocument();
    expect(screen.getByText('الفئة العمرية · الشباب')).toBeInTheDocument();
    expect(screen.getByText('نعم')).toBeInTheDocument();
    expect(screen.getByText('لا')).toBeInTheDocument();
    // A study with no cohort breakdown reads as the translated "all adults".
    const allAdults = i18n.t('dashboard:survey.allAdults');
    expect(screen.getByText(`${allAdults} · ${allAdults}`)).toBeInTheDocument();
    expect(translateLabels).toHaveBeenCalledTimes(1);
  });

  it('shows the source text in English without asking the server', async () => {
    await i18n.changeLanguage('en');
    renderSurvey();
    expect(screen.getByText('Do you trust the news?')).toBeInTheDocument();
    expect(screen.getByText('Age Group · Young Adults')).toBeInTheDocument();
    expect(translateLabels).not.toHaveBeenCalled();
  });

  it('renders nothing without observations', () => {
    const { container } = renderSurvey([]);
    expect(container).toBeEmptyDOMElement();
  });
});
