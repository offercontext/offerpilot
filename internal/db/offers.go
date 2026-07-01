package db

import (
	"database/sql"
	"time"
)

// computeTotalCash fills the derived TotalCash field.
func computeTotalCash(o *Offer) {
	o.TotalCash = o.BaseMonthly*o.MonthsPerYear + o.SigningBonus
}

// normalizeOffer applies default values for optional fields.
func normalizeOffer(o *Offer) {
	if o.MonthsPerYear == 0 {
		o.MonthsPerYear = 12
	}
	if o.Status == "" {
		o.Status = "pending"
	}
}

// CreateOffer inserts a new offer.
func (db *Database) CreateOffer(o *Offer) error {
	normalizeOffer(o)
	now := time.Now()
	res, err := db.conn.Exec(
		`INSERT INTO offers (application_id, company_name, position_name, status, base_monthly, months_per_year, signing_bonus, equity, perks, deadline, notes, assessment, created_at, updated_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
		nullableInt64(o.ApplicationID), o.CompanyName, o.PositionName, o.Status,
		o.BaseMonthly, o.MonthsPerYear, o.SigningBonus, o.Equity, o.Perks,
		o.Deadline, o.Notes, o.Assessment, now, now,
	)
	if err != nil {
		return err
	}
	o.ID, _ = res.LastInsertId()
	o.CreatedAt = now
	o.UpdatedAt = now
	computeTotalCash(o)
	return nil
}

func scanOffer(scan func(dest ...interface{}) error) (*Offer, error) {
	var o Offer
	var appID sql.NullInt64
	if err := scan(&o.ID, &appID, &o.CompanyName, &o.PositionName, &o.Status,
		&o.BaseMonthly, &o.MonthsPerYear, &o.SigningBonus, &o.Equity, &o.Perks,
		&o.Deadline, &o.Notes, &o.Assessment, &o.CreatedAt, &o.UpdatedAt); err != nil {
		return nil, err
	}
	if appID.Valid {
		v := appID.Int64
		o.ApplicationID = &v
	}
	computeTotalCash(&o)
	return &o, nil
}

const offerCols = `id, application_id, company_name, position_name, status, base_monthly, months_per_year, signing_bonus, equity, perks, deadline, notes, assessment, created_at, updated_at`

// GetOffer retrieves a single offer by ID.
func (db *Database) GetOffer(id int64) (*Offer, error) {
	row := db.conn.QueryRow(`SELECT `+offerCols+` FROM offers WHERE id = ?`, id)
	return scanOffer(row.Scan)
}

// ListOffers lists offers, optionally filtered by status (pass "" for all). Newest first.
func (db *Database) ListOffers(status string) ([]Offer, error) {
	query := `SELECT ` + offerCols + ` FROM offers`
	var args []interface{}
	if status != "" {
		query += ` WHERE status = ?`
		args = append(args, status)
	}
	query += ` ORDER BY created_at DESC`
	rows, err := db.conn.Query(query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Offer
	for rows.Next() {
		o, err := scanOffer(rows.Scan)
		if err != nil {
			return nil, err
		}
		out = append(out, *o)
	}
	return out, nil
}

// UpdateOffer updates mutable fields (never id/application_id).
func (db *Database) UpdateOffer(o *Offer) error {
	normalizeOffer(o)
	now := time.Now()
	_, err := db.conn.Exec(
		`UPDATE offers SET company_name = ?, position_name = ?, status = ?, base_monthly = ?, months_per_year = ?, signing_bonus = ?, equity = ?, perks = ?, deadline = ?, notes = ?, assessment = ?, updated_at = ? WHERE id = ?`,
		o.CompanyName, o.PositionName, o.Status, o.BaseMonthly, o.MonthsPerYear,
		o.SigningBonus, o.Equity, o.Perks, o.Deadline, o.Notes, o.Assessment, now, o.ID,
	)
	if err != nil {
		return err
	}
	o.UpdatedAt = now
	computeTotalCash(o)
	return nil
}

// DeleteOffer removes an offer by ID.
func (db *Database) DeleteOffer(id int64) error {
	_, err := db.conn.Exec(`DELETE FROM offers WHERE id = ?`, id)
	return err
}
