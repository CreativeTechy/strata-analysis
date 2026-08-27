import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import TermChipsField from './TermChipsField.jsx'

describe('TermChipsField', () => {
  it('renders existing values as removable chips', () => {
    render(<TermChipsField label="Topics" placeholder="Add" values={['ev', 'charging']} onChange={vi.fn()} />)
    expect(screen.getByText('ev')).toBeInTheDocument()
    expect(screen.getByText('charging')).toBeInTheDocument()
  })

  it('adds a manually typed value on submit', () => {
    const onChange = vi.fn()
    render(<TermChipsField label="Topics" placeholder="Add" values={['ev']} onChange={onChange} />)
    const input = screen.getByPlaceholderText('Add')
    fireEvent.change(input, { target: { value: 'battery' } })
    fireEvent.submit(input.closest('form'))
    expect(onChange).toHaveBeenCalledWith(['ev', 'battery'])
  })

  it('does not add a duplicate value', () => {
    const onChange = vi.fn()
    render(<TermChipsField label="Topics" placeholder="Add" values={['ev']} onChange={onChange} />)
    fireEvent.change(screen.getByPlaceholderText('Add'), { target: { value: 'ev' } })
    fireEvent.submit(screen.getByPlaceholderText('Add').closest('form'))
    expect(onChange).not.toHaveBeenCalled()
  })

  it('removes a value when its remove button is clicked', () => {
    const onChange = vi.fn()
    render(<TermChipsField label="Topics" placeholder="Add" values={['ev', 'charging']} onChange={onChange} />)
    fireEvent.click(screen.getByLabelText('Remove ev'))
    expect(onChange).toHaveBeenCalledWith(['charging'])
  })

  it('offers only options not already selected', () => {
    render(
      <TermChipsField
        label="Topics"
        placeholder="Add"
        values={['ev']}
        onChange={vi.fn()}
        options={['ev', 'battery', 'charging']}
      />
    )
    const select = screen.getByRole('combobox')
    expect(screen.queryByRole('option', { name: 'ev' })).not.toBeInTheDocument()
    expect(select).toHaveTextContent('battery')
    expect(select).toHaveTextContent('charging')
  })
})
