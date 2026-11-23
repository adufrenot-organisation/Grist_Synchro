#!/usr/bin/env python3
import os,sys,json,urllib.request,urllib.error,time,uuid,traceback,smtplib,ssl,hashlib
from email.message import EmailMessage
from datetime import datetime, timezone, date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HOST=os.environ.get("GRIST_HOST","").rstrip("/")
KEY=os.environ.get("RH_SYNC_API_KEY","").strip()
DEMANDES=os.environ.get("DEMANDES_DOC_ID","").strip()
COCKPIT=os.environ.get("COCKPIT_DOC_ID","").strip()
if not all([HOST,KEY,DEMANDES,COCKPIT]):
    print("Définir GRIST_HOST, RH_SYNC_API_KEY, DEMANDES_DOC_ID et COCKPIT_DOC_ID.",file=sys.stderr);sys.exit(1)

SMTP_ENABLED=os.environ.get("SMTP_ENABLED","false").strip().lower() in ("1","true","yes","oui")
SMTP_HOST=os.environ.get("SMTP_HOST","").strip()
SMTP_PORT=int(os.environ.get("SMTP_PORT","587"))
SMTP_USER=os.environ.get("SMTP_USER","").strip()
SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD","")
SMTP_FROM=os.environ.get("SMTP_FROM",SMTP_USER).strip()
SMTP_FROM_NAME=os.environ.get("SMTP_FROM_NAME","RH - Demandes").strip()
SMTP_SECURITY=os.environ.get("SMTP_SECURITY","starttls").strip().lower() # starttls | ssl | none
SMTP_TIMEOUT=int(os.environ.get("SMTP_TIMEOUT_SECONDS","20"))
PORTAL_URL=os.environ.get("PORTAL_URL","").strip()
COCKPIT_URL=os.environ.get("COCKPIT_URL","").strip()
STATE_FILE=os.environ.get("STATE_FILE","/data/state.json").strip()
NOTIFY_EXISTING_ON_FIRST_RUN=os.environ.get("NOTIFY_EXISTING_ON_FIRST_RUN","false").strip().lower() in ("1","true","yes","oui")


# Horodatage explicite de chaque événement métier et des résultats de cycle.
# RH_SYNC_TIMEZONE est optionnel (Europe/Paris par défaut), UTC en repli.
TZ_NAME=os.environ.get("RH_SYNC_TIMEZONE","Europe/Paris").strip() or "Europe/Paris"
try:
    LOG_TZ=ZoneInfo(TZ_NAME)
except ZoneInfoNotFoundError:
    LOG_TZ=timezone.utc
    print(f"AVERTISSEMENT: fuseau {TZ_NAME!r} indisponible, utilisation UTC",file=sys.stderr,flush=True)

def timestamp():
    return datetime.now(LOG_TZ).isoformat(timespec="seconds")

class TimestampedLog(list):
    """Conserve le format des appels log.append existants, horodate à l'entrée."""
    def append(self, message):
        value=str(message)
        upper=value.upper()
        if any(k in upper for k in ("AVERTISSEMENT", "WARN", "EMAIL ÉCHEC")):
            level="AVERTISSEMENT"
        elif any(k in upper for k in ("ERREUR", "ECHEC", "ÉCHEC", "IMPOSSIBLE", "HTTP 4", "HTTP 5")):
            level="ERREUR"
        else:
            level="INFO"
        super().append(f"{timestamp()} [{level}] {value}")

def load_state():
    try:
        with open(STATE_FILE,"r",encoding="utf-8") as f:
            data=json.load(f)
            if isinstance(data,dict): return data
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"WARN lecture état {STATE_FILE}: {e}",file=sys.stderr)
    return {"portal":{},"cockpit":{}}

def save_state(state):
    folder=os.path.dirname(STATE_FILE)
    if folder: os.makedirs(folder,exist_ok=True)
    tmp=STATE_FILE+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(state,f,ensure_ascii=False,indent=2,sort_keys=True)
    os.replace(tmp,STATE_FILE)

def fingerprint(payload):
    raw=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

STATE=load_state()


def api(doc,path,method="GET",body=None):
    data=None if body is None else json.dumps(body).encode()
    q=urllib.request.Request(f"{HOST}/api/docs/{doc}{path}",data=data,method=method,
      headers={"Authorization":"Bearer "+KEY,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(q,timeout=45) as r:
            raw=r.read(); return json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: HTTP {e.code} - {e.read().decode(errors='replace')}") from e

def rec(doc,t): return api(doc,f"/tables/{t}/records").get("records",[])
def columns(doc,t): return api(doc,f"/tables/{t}/columns").get("columns",[])
def patch(doc,t,i,f): return api(doc,f"/tables/{t}/records","PATCH",{"records":[{"id":i,"fields":f}]})
def create(doc,t,f): return api(doc,f"/tables/{t}/records","POST",{"records":[{"fields":f}]})
def delete_records(doc,t,ids):
    ids=[int(x) for x in ids if x is not None]
    if not ids: return {}
    return api(doc,f"/tables/{t}/records/delete","POST",ids)
def n(v): return str(v or "").strip()
def lo(v): return n(v).lower()
def F(r,k,d=None): return (r.get("fields") or {}).get(k,d)
def now(): return int(time.time())
def refid(v):
    if isinstance(v,int): return v
    if isinstance(v,list) and len(v)>=2 and v[0] in ("L","l"): return v[1]
    try: return int(v)
    except (TypeError,ValueError): return None

def idx(rows,key,fn=n):
    out={}; dup=set()
    for r in rows:
        v=fn(F(r,key))
        if not v: continue
        if v in out: dup.add(v)
        else: out[v]=r
    return out,dup

def bool_value(v, default=False):
    if isinstance(v,bool): return v
    if v is None: return default
    return n(v).casefold() in ("1","true","yes","oui","on")

def date_key(v):
    """Normalise une valeur Grist Date/Any en YYYY-MM-DD."""
    if v in (None,""): return ""
    if isinstance(v,(int,float)):
        try:return datetime.fromtimestamp(float(v),timezone.utc).date().isoformat()
        except (ValueError,OSError,OverflowError):return ""
    raw=n(v)
    if len(raw)>=10:
        try:return date.fromisoformat(raw[:10]).isoformat()
        except ValueError:pass
    try:return datetime.fromisoformat(raw.replace("Z","+00:00")).date().isoformat()
    except ValueError:return ""

def date_epoch(v):
    key=date_key(v)
    if not key:return None
    d=date.fromisoformat(key)
    return int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp())

def daterange_bounds(start_value,end_value):
    a=date_key(start_value); b=date_key(end_value)
    if not a or not b: raise ValueError("Période de synchronisation invalide")
    if a>b: raise ValueError("Date_Debut postérieure à Date_Fin")
    return a,b

def in_date_range(v,a,b):
    k=date_key(v)
    return bool(k and a<=k<=b)

def current_year_bounds():
    today=datetime.now(LOG_TZ).date()
    return date(today.year,1,1).isoformat(),date(today.year,12,31).isoformat()

def normalized_status(v):
    return n(v).upper().replace("É","E").replace("È","E").replace("Ê","E")

def is_validated_status(v):
    return normalized_status(v) in {"VALIDE","VALIDEE","ACCEPTE","ACCEPTEE","APPROUVE","APPROUVEE"}

def table_column_ids(doc, table_name):
    return {c.get("id") for c in columns(doc,table_name)}

def filter_existing_fields(fields, allowed):
    return {k:v for k,v in fields.items() if k in allowed}

def send_mail(to_addrs, subject, text, log):
    if not SMTP_ENABLED: return False
    if isinstance(to_addrs,str): to_addrs=[to_addrs]
    to_addrs=sorted({n(x) for x in to_addrs if n(x)})
    if not to_addrs: return False
    if not SMTP_HOST or not SMTP_FROM:
        log.append("EMAIL: SMTP activé mais SMTP_HOST/SMTP_FROM incomplet."); return False
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=f"{SMTP_FROM_NAME} <{SMTP_FROM}>"; msg["To"]=", ".join(to_addrs)
    msg.set_content(text)
    try:
        if SMTP_SECURITY=="ssl":
            s=smtplib.SMTP_SSL(SMTP_HOST,SMTP_PORT,timeout=SMTP_TIMEOUT,context=ssl.create_default_context())
        else:
            s=smtplib.SMTP(SMTP_HOST,SMTP_PORT,timeout=SMTP_TIMEOUT)
            if SMTP_SECURITY=="starttls": s.starttls(context=ssl.create_default_context())
        with s:
            if SMTP_USER: s.login(SMTP_USER,SMTP_PASSWORD)
            s.send_message(msg)
        log.append(f"EMAIL envoyé à {', '.join(to_addrs)}: {subject}")
        return True
    except Exception as e:
        log.append(f"EMAIL échec vers {', '.join(to_addrs)}: {e}")
        return False

def short_value(value, limit=140):
    """Représentation bornée pour le diagnostic (ne journalise pas les adresses)."""
    raw=repr(value)
    return raw if len(raw)<=limit else raw[:limit]+"…"


def team_equipo_value(person):
    """Renvoie la valeur de la colonne technique Grist Team.equipe.

    La casse est significative dans l'API Grist : « Equipe » (titre affiché)
    n'est pas l'identifiant « equipe » renvoyé dans les données Cockpit.
    """
    fields=(person or {}).get("fields") or {}
    if "equipe" in fields:
        return fields["equipe"]
    # Compatibilité avec d'autres documents au schéma historique.
    return fields.get("Equipe")


def team_diagnostic(person, team_index):
    """Explicite les colonnes reçues de l'API, sans exposer les emails ni les noms."""
    fields=(person or {}).get("fields") or {}
    related={k:short_value(v) for k,v in fields.items()
             if any(token in k.casefold() for token in ("equip", "équip", "team_ref"))}
    value=team_equipo_value(person)
    resolved, reason=resolve_team_id(value,team_index)
    return {"team_row":person.get("id") if person else None,
            "Equipe_raw":short_value(value),"Equipe_type":type(value).__name__,
            "related_fields":related,"fields_available":sorted(fields.keys()),
            "resolved_team_ref_id":resolved,"reason":reason}


def describe_request_team(log, request_id, person, team_index, result=None):
    diag=team_diagnostic(person,team_index)
    prefix=f"DEMANDE #{request_id} | Team #{diag['team_row']}"
    message=(f"{prefix} | Team.equipe={diag['Equipe_raw']} ({diag['Equipe_type']})"
             f" | colonnes_equipe={json.dumps(diag['related_fields'],ensure_ascii=False)}"
             f" | Team_ref.id={diag['resolved_team_ref_id'] or '-'}"
             f" | résultat={result or diag['reason'] or 'trouvé'}")
    log.append(message)
    if diag['Equipe_raw']=='None' or diag['Equipe_raw']=="''":
        log.append(f"DIAGNOSTIC {prefix} | Team.equipe absent/vide dans la réponse API"
                   f" | colonnes_disponibles={json.dumps(diag['fields_available'],ensure_ascii=False)}"
                   f" | vérifier l'identifiant technique de la colonne dans Grist (pas seulement le libellé affiché)")
    return diag


def team_ref_details(rows):
    by_id={}; by_label={}; ambiguous=set()
    for r in rows:
        f=r.get("fields") or {}
        label=next((n(f.get(k)) for k in ("libelle","Libelle","Libellé","libellé") if n(f.get(k))),"")
        code=next((n(f.get(k)) for k in ("Code","code","Equipe_Code") if n(f.get(k))),"")
        by_id[r["id"]]={"label":label,"code":code}
        if label:
            key=label.casefold()
            if key in by_label: ambiguous.add(key)
            else: by_label[key]=r["id"]
    return by_id,by_label,ambiguous

def resolve_team_name(value, team_refs):
    by_id,by_label,ambiguous=team_ref_details(team_refs)
    rid=refid(value)
    if rid in by_id:
        d=by_id[rid]
        return d.get("label") or d.get("code") or str(rid),rid,""
    label=n(value)
    if not label:return "",None,"équipe vide"
    key=label.casefold()
    if key in ambiguous:return label,None,f"libellé d'équipe ambigu : {label}"
    if key in by_label:
        rid=by_label[key];d=by_id[rid]
        return d.get("label") or label,rid,""
    return label,None,f"équipe introuvable dans Team_ref : {label}"

def sync_resources(log):
    """Cockpit.Team MASTER -> Ressources, avec nom d'équipe résolu depuis Team_ref."""
    src,dst=rec(COCKPIT,"Team"),rec(DEMANDES,"Ressources")
    try: team_refs=rec(COCKPIT,"Team_ref")
    except Exception as exc:
        team_refs=[];log.append(f"AVERTISSEMENT Team_ref non lisible: {exc}")
    du,ddup=idx(dst,"UUID_Ressource"); de,_=idx(dst,"Email",lo)
    c=u=e=w=0
    for r in src:
        f=r["fields"]; uid=n(f.get("UUID_Ressource")); mail=lo(f.get("email") or f.get("Email"))
        if not uid:
            uid=str(uuid.uuid4())
            try:
                patch(COCKPIT,"Team",r["id"],{"UUID_Ressource":uid}); f["UUID_Ressource"]=uid
                w+=1; log.append(f"INFO Team #{r['id']}: UUID_Ressource généré.")
            except Exception as x:
                e+=1; log.append(f"Team #{r['id']}: impossible de créer UUID_Ressource: {x}"); continue
        if uid in ddup:
            e+=1; log.append(f"UUID_Ressource dupliqué dans Ressources: {uid}"); continue
        d=du.get(uid)
        if not d and mail:
            candidate=de.get(mail)
            if candidate and not n(F(candidate,"UUID_Ressource")): d=candidate
        if not mail:
            w+=1; log.append(f"AVERTISSEMENT Team #{r['id']} ({uid}): Email vide; ressource synchronisée, mais connexion utilisateur impossible tant que l'email reste vide.")
        raw_team=team_equipo_value(r)
        team_name,team_ref_id,team_error=resolve_team_name(raw_team,team_refs)
        if team_error and raw_team not in (None,""):
            w+=1;log.append(f"AVERTISSEMENT Team #{r['id']} ({uid}): {team_error}; valeur conservée={short_value(team_name)}")
        if not team_name:
            team_name=n(f.get("Equipe_Code"))
        fields={"UUID_Ressource":uid,"Email":f.get("email") or f.get("Email") or "","Nom":f.get("nom") or f.get("Nom"),
          "Profil":f.get("Profil") or f.get("profil"),"Equipe_Code":team_name,
          "Actif":f.get("Actif",True),"Source_Team_ID":r["id"],
          "Derniere_Sync":now(),"Erreur_Sync":""}
        try:
            if d:
                patch(DEMANDES,"Ressources",d["id"],fields); u+=1
                log.append(f"RESSOURCE Team #{r['id']} -> Ressources #{d['id']} | action=MISE_A_JOUR | UUID={uid} | équipe={team_name or '-'} | Team_ref={team_ref_id or '-'}")
            else:
                created=create(DEMANDES,"Ressources",fields); c+=1
                log.append(f"RESSOURCE Team #{r['id']} | action=CREATION | UUID={uid} | équipe={team_name or '-'} | Team_ref={team_ref_id or '-'}")
        except Exception as x:
            e+=1; log.append(f"Ressource {uid}: {x}")
    return {"created":c,"updated":u,"warnings":w,"errors":e}

def manager_emails_for_person(person, teams_by_id, mappings, log):
    """Résout les managers actifs via Managers_Equipes. Supporte Equipe Ref:Team_ref."""
    team_ref=refid(team_equipo_value(person))
    if not team_ref: return []
    emails=[]
    for m in mappings:
        if F(m,"Actif",True) is False: continue
        if refid(F(m,"Equipe")) != team_ref: continue
        direct=n(F(m,"Manager_Email"))
        if direct: emails.append(direct); continue
        manager=teams_by_id.get(refid(F(m,"Manager")))
        if manager:
            mail=n(F(manager,"email") or F(manager,"Email"))
            if mail: emails.append(mail)
    return sorted(set(emails))

def local_motif_code(request_fields, local_motifs_by_id):
    code=n(request_fields.get("Motif_Code"))
    if code: return code
    mid=refid(request_fields.get("Motif"))
    if mid and mid in local_motifs_by_id:
        return n(F(local_motifs_by_id[mid],"Code"))
    return ""

def requester_email(local_person):
    return n(F(local_person,"Email") or F(local_person,"email"))

def requester_label(local_person):
    return n(F(local_person,"Nom") or F(local_person,"nom") or requester_email(local_person)) or "Collaborateur"

def request_summary_text(f, ref):
    return (f"Référence : {ref}\n"
            f"Statut : {n(f.get('Statut') or 'EN_ATTENTE')}\n"
            f"Type : {n(f.get('Type'))}\n"
            f"Période : {n(f.get('Date_Debut'))} → {n(f.get('Date_Fin'))}\n")


def team_ref_index(rows):
    """Index unique des libellés Team_ref, sans déduire d'identifiants."""
    ids={r["id"] for r in rows}
    by_label={}; ambiguous=set()
    for r in rows:
        fields=r.get("fields") or {}
        label=next((fields[k] for k in ("libelle","Libelle","Libellé","libellé") if k in fields),None)
        key=n(label).casefold()
        if not key: continue
        if key in by_label: ambiguous.add(key)
        else: by_label[key]=r["id"]
    return ids,by_label,ambiguous


def resolve_team_id(value, team_index):
    """Accepte l'id Ref Grist ou un libellé; refuse les libellés ambigus."""
    ids,by_label,ambiguous=team_index
    rid=refid(value)
    if rid in ids:return rid,""
    label=n(value)
    if not label:return None,"équipe vide"
    key=label.casefold()
    if key in ambiguous:return None,f"libellé d'équipe ambigu : {label}"
    if key in by_label:return by_label[key],""
    return None,f"équipe introuvable dans Team_ref : {label}"


def sync_requests(log):
    src,dst=rec(DEMANDES,"Demandes_RH"),rec(COCKPIT,"Demandes_RH")
    teams,motifs,lres=rec(COCKPIT,"Team"),rec(COCKPIT,"Motifs_RH"),rec(DEMANDES,"Ressources")
    team_index=team_ref_index(rec(COCKPIT,"Team_ref"))
    try: local_motifs=rec(DEMANDES,"Motifs_RH")
    except Exception: local_motifs=[]
    try: mappings=rec(COCKPIT,"Managers_Equipes")
    except Exception as x: mappings=[]; log.append(f"AVERTISSEMENT Managers_Equipes non lisible: {x}")
    teams_by_id={r["id"]:r for r in teams}
    local_motifs_by_id={r["id"]:r for r in local_motifs}
    di,ddup=idx(dst,"UUID_Demande"); tu,tudup=idx(teams,"UUID_Ressource"); ti,_=idx(teams,"email",lo); mi,mdup=idx(motifs,"Code")
    lr={r["id"]:r for r in lres};c=u=e=mail_count=0
    for r in src:
        f=r["fields"]; uid=n(f.get("UUID_Demande"))
        if not uid: e+=1;log.append(f"Demande #{r['id']}: UUID vide.");continue
        if uid in ddup:e+=1;log.append(f"UUID dupliqué Cockpit: {uid}");continue
        local_person=lr.get(refid(f.get("Demandeur")) or f.get("Demandeur"),{})
        resource_uuid=n(F(local_person,"UUID_Ressource"))
        if resource_uuid and resource_uuid in tudup:
            e+=1;log.append(f"{uid}: UUID_Ressource dupliqué dans Cockpit.Team: {resource_uuid}");continue
        person=tu.get(resource_uuid) if resource_uuid else None
        if not person: person=ti.get(lo(F(local_person,"Email")))
        code=local_motif_code(f,local_motifs_by_id); motif=mi.get(code)
        if not person:e+=1;log.append(f"{uid}: ressource absente du Cockpit (UUID/email introuvable).");continue
        if code in mdup:e+=1;log.append(f"{uid}: motif {code} dupliqué dans Cockpit.");continue
        if not motif:e+=1;log.append(f"{uid}: motif {code or '?'} absent du Cockpit.");continue

        # Empreinte uniquement des champs dont le portail est maître.
        portal_payload={"Reference":f.get("Reference"),"Demandeur_UUID":resource_uuid or lo(F(local_person,"Email")),
          "Type":f.get("Type"),"Date_Debut":f.get("Date_Debut"),"Date_Fin":f.get("Date_Fin"),
          "Motif_Code":code,"Commentaire_Demandeur":f.get("Commentaire_Demandeur"),
          "Date_Demande":f.get("Date_Demande"),"Statut":n(f.get("Statut") or "EN_ATTENTE").upper(),
          "AutoValidation":bool_value(f.get("AutoValidation"),False)}
        fp=fingerprint(portal_payload)
        previous=STATE.setdefault("portal",{}).get(uid)
        d=di.get(uid)
        is_create=d is None
        changed=(previous is not None and previous!=fp)
        first_seen=(previous is None)
        needs_write=is_create or changed or first_seen

        team_id,team_error=resolve_team_id(team_equipo_value(person),team_index)
        if not team_id:
            log.append(f"AVERTISSEMENT demande {uid}: Team #{person['id']} : {team_error}")
            describe_request_team(log,r['id'],person,team_index,team_error)
        fields={"Reference":f.get("Reference"),"Demandeur":person["id"],"Type":f.get("Type"),
          "Date_Debut":f.get("Date_Debut"),"Date_Fin":f.get("Date_Fin"),"Motif":motif["id"],
          "Commentaire_Demandeur":f.get("Commentaire_Demandeur"),"Date_Demande":f.get("Date_Demande"),
          "UUID_Demande":uid,"Statut":f.get("Statut") or "EN_ATTENTE",
          "AutoValidation":bool_value(f.get("AutoValidation"),False)}
        if team_id and (not d or not n(F(d,"Equipe"))):
            fields["Equipe"]=team_id
        try:
            if needs_write:
                if d:
                    patch(COCKPIT,"Demandes_RH",d["id"],fields);u+=1
                    log.append(f"DEMANDE {uid} | action=MISE_A_JOUR Cockpit.Demandes_RH #{d['id']} | demandeur=Team #{person['id']} | Equipe={team_id or 'NON_RESOLUE'} | motif={code}")
                else:
                    create(COCKPIT,"Demandes_RH",fields);c+=1
                    log.append(f"DEMANDE {uid} | action=CREATION Cockpit.Demandes_RH | demandeur=Team #{person['id']} | Equipe={team_id or 'NON_RESOLUE'} | motif={code}")
                # On mémorise seulement APRES réussite de la synchro.
                STATE["portal"][uid]=fp; save_state(STATE)
            elif team_id and d and n(F(d,"Equipe")):
                log.append(f"DEMANDE {uid} | action=INCHANGEE | équipe existante conservée={short_value(F(d,'Equipe'))}")

            # Notification uniquement sur création réelle, ou modification détectée après bootstrap.
            notify=is_create or changed or (first_seen and NOTIFY_EXISTING_ON_FIRST_RUN)
            if notify and needs_write:
                ref=n(f.get("Reference")) or uid
                status=n(f.get("Statut") or "EN_ATTENTE")
                action="enregistrée" if is_create else "mise à jour"
                reqmail=requester_email(local_person)
                portal_link=f"\nPortail : {PORTAL_URL}\n" if PORTAL_URL else ""
                if reqmail:
                    body=(f"Votre demande RH a bien été {action} et synchronisée.\n\n"
                          +request_summary_text({**f,"Statut":status},ref)+portal_link)
                    if send_mail(reqmail,f"[RH] Demande {ref} — {action}",body,log): mail_count+=1
                elif SMTP_ENABLED: log.append(f"EMAIL {uid}: email demandeur absent.")

                managers=manager_emails_for_person(person,teams_by_id,mappings,log)
                if managers:
                    cockpit_link=f"\nCockpit : {COCKPIT_URL}\n" if COCKPIT_URL else ""
                    demandeur=requester_label(local_person)
                    if is_create:
                        intro="Une nouvelle demande RH est en attente de validation."
                        subject=f"[RH] Nouvelle demande {ref} — {status}"
                    else:
                        intro="Une demande RH existante a été modifiée par le demandeur et synchronisée."
                        subject=f"[RH] Demande modifiée {ref} — {status}"
                    body=(f"{intro}\n\nDemandeur : {demandeur}\n"
                          +request_summary_text({**f,"Statut":status},ref)+cockpit_link)
                    if send_mail(managers,subject,body,log): mail_count+=1
                elif SMTP_ENABLED: log.append(f"EMAIL {uid}: aucun manager actif avec email trouvé pour l'équipe.")
        except Exception as x:e+=1;log.append(f"Demande {uid}: {x}")
    return {"created":c,"updated":u,"emails":mail_count,"errors":e}

def presence_target_id_column(target_columns):
    if "Source_Presence_ID" in target_columns:return "Source_Presence_ID"
    if "Source_Feuille_ID" in target_columns:return "Source_Feuille_ID"
    raise RuntimeError("PLANNING_PRESENCE doit contenir Source_Presence_ID ou Source_Feuille_ID")

def sync_presence_period(log,start_value,end_value,resource_uuid=None,force_full=False,reason="MANUELLE"):
    """Réconcilie Cockpit.Presences -> Demandes.PLANNING_PRESENCE sur une période.

    Clé métier d'upsert V3.9 : (Ressource locale, Date).
    Cockpit.Presences reste la source maître. Source_Presence_ID/Source_Feuille_ID
    est conservé uniquement pour la traçabilité.

    Les lignes supprimées côté Cockpit sont supprimées du planning cible dans la période,
    uniquement pour les ressources concernées par le filtre éventuel.
    Si Cockpit contient plusieurs présences pour le même couple Ressource+Date,
    la clé est signalée en conflit et n'est ni écrasée ni supprimée côté cible.
    """
    a,b=daterange_bounds(start_value,end_value)
    src=rec(COCKPIT,"Presences")
    teams=rec(COCKPIT,"Team")
    motifs=rec(COCKPIT,"Motifs_RH")
    team_refs=rec(COCKPIT,"Team_ref")
    local_resources=rec(DEMANDES,"Ressources")
    target=rec(DEMANDES,"PLANNING_PRESENCE")
    target_columns=table_column_ids(DEMANDES,"PLANNING_PRESENCE")
    source_id_col=presence_target_id_column(target_columns)

    teams_by_id={r["id"]:r for r in teams}
    motifs_by_id={r["id"]:r for r in motifs}
    local_by_uuid,_=idx(local_resources,"UUID_Ressource")
    local_by_email,_=idx(local_resources,"Email",lo)
    local_by_id={r["id"]:r for r in local_resources}
    team_name_by_team_id={}
    for team in teams:
        name,_,_=resolve_team_name(team_equipo_value(team),team_refs)
        team_name_by_team_id[team["id"]]=name or n(F(team,"Equipe_Code"))

    selected_team_ids=None
    if resource_uuid:
        selected_team_ids={r["id"] for r in teams if n(F(r,"UUID_Ressource"))==n(resource_uuid)}
        if not selected_team_ids:
            log.append(f"AVERTISSEMENT planning ciblé: UUID_Ressource introuvable dans Cockpit.Team: {resource_uuid}")

    source_rows=[]
    for row in src:
        if not in_date_range(F(row,"Date"),a,b):continue
        team_id=refid(F(row,"Ressource"))
        if selected_team_ids is not None and team_id not in selected_team_ids:continue
        source_rows.append(row)

    # Index cible par clé métier (Ressource locale, Date), et non plus par ID source Cockpit.
    existing_by_key={}
    duplicate_target_ids=[]
    for row in target:
        local_id=refid(F(row,"Ressource"))
        dkey=date_key(F(row,"Date"))
        if not local_id or not dkey:continue
        key=(local_id,dkey)
        if key in existing_by_key:
            duplicate_target_ids.append(row["id"])
        else:
            existing_by_key[key]=row
    if duplicate_target_ids:
        log.append(f"AVERTISSEMENT PLANNING_PRESENCE: {len(duplicate_target_ids)} doublon(s) Ressource+Date détecté(s); ils seront nettoyés dans la période synchronisée.")

    # Résolution des lignes Cockpit vers la clé métier locale avant écriture.
    # Une incohérence Cockpit sur une même clé ne doit jamais être arbitrée silencieusement.
    source_by_key={}
    source_conflicts={}
    source_meta={}
    errors=warnings=0
    for row in source_rows:
        sid=row["id"]
        sf=row.get("fields") or {}
        team_id=refid(sf.get("Ressource")); team=teams_by_id.get(team_id)
        if not team:
            errors+=1;log.append(f"ERREUR Presence #{sid}: Ressource Team introuvable ({team_id})");continue
        uid=n(F(team,"UUID_Ressource")); mail=lo(F(team,"email") or F(team,"Email"))
        local=local_by_uuid.get(uid) if uid else None
        if not local and mail:local=local_by_email.get(mail)
        if not local:
            errors+=1;log.append(f"ERREUR Presence #{sid}: Ressource locale introuvable pour Team #{team_id} UUID={uid or '-'}");continue
        dkey=date_key(sf.get("Date"))
        if not dkey:
            errors+=1;log.append(f"ERREUR Presence #{sid}: Date invalide ({sf.get('Date')!r})");continue
        key=(local["id"],dkey)
        source_meta[key]=(local,team_id)
        if key in source_by_key:
            first=source_by_key.pop(key)
            source_conflicts[key]=[first,row]
        elif key in source_conflicts:
            source_conflicts[key].append(row)
        else:
            source_by_key[key]=row

    for (local_id,dkey),rows in source_conflicts.items():
        local=local_by_id.get(local_id)
        label=n(F(local,"Nom_Complet") or F(local,"Nom") or F(local,"Email") or local_id)
        ids=",".join(str(r["id"]) for r in rows)
        errors+=1
        log.append(f"ERREUR CONFLIT_SOURCE Cockpit.Presences: Ressource={label} Date={dkey} lignes={ids}; aucune valeur n'est choisie arbitrairement")

    created=updated=deleted=0
    seen_keys=set(source_by_key) | set(source_conflicts)
    touched_local_resource_ids=set()

    for key,row in source_by_key.items():
        sid=row["id"]
        sf=row.get("fields") or {}
        local_id,dkey=key
        local,team_id=source_meta[key]
        touched_local_resource_ids.add(local_id)
        motif=motifs_by_id.get(refid(sf.get("Motif")))
        motif_code=n(F(motif,"Code") or F(motif,"code")) if motif else ""
        motif_label=n(F(motif,"Libelle") or F(motif,"libelle") or F(motif,"Libellé")) if motif else ""
        fields={
            "Ressource":local_id,"Date":date_epoch(dkey),"Statut":sf.get("Statut") or "",
            "Libelle":motif_label,"Motif_Code":motif_code,"Equipe_Code":team_name_by_team_id.get(team_id) or "",
            source_id_col:sid,"Derniere_Sync":now(),"Erreur_Sync":"",
            "Commentaire":sf.get("Commentaire") or "","Source":sf.get("Source") or ""
        }
        fields=filter_existing_fields(fields,target_columns)
        try:
            current=existing_by_key.get(key)
            if current:
                patch(DEMANDES,"PLANNING_PRESENCE",current["id"],fields);updated+=1
                log.append(f"PLANNING UPDATE | Ressource={local_id} | Date={dkey} | SourcePresence={sid}")
            else:
                create(DEMANDES,"PLANNING_PRESENCE",fields);created+=1
                log.append(f"PLANNING CREATE | Ressource={local_id} | Date={dkey} | SourcePresence={sid}")
        except Exception as exc:
            errors+=1;log.append(f"ERREUR Presence #{sid}: écriture planning impossible pour Ressource={local_id} Date={dkey}: {exc}")

    # Réconciliation des suppressions dans la période par clé métier Ressource+Date.
    # Les clés en conflit côté Cockpit sont protégées : on n'écrase ni ne supprime la valeur locale.
    delete_ids=[]
    for row in target:
        if not in_date_range(F(row,"Date"),a,b):continue
        local_id=refid(F(row,"Ressource"))
        dkey=date_key(F(row,"Date"))
        if not local_id or not dkey:continue
        if resource_uuid:
            local=local_by_id.get(local_id)
            if not local or n(F(local,"UUID_Ressource"))!=n(resource_uuid):continue
        key=(local_id,dkey)
        if key not in seen_keys:
            delete_ids.append(row["id"])
            log.append(f"PLANNING DELETE | Ressource={local_id} | Date={dkey} | absent de Cockpit.Presences")

    # Dédoublonnage local : conservation de la première ligne indexée pour la clé,
    # suppression des lignes supplémentaires uniquement sur la période / ressource traitée.
    duplicate_set=set(duplicate_target_ids)
    for row in target:
        if row["id"] not in duplicate_set or not in_date_range(F(row,"Date"),a,b):continue
        local_id=refid(F(row,"Ressource"))
        if resource_uuid:
            local=local_by_id.get(local_id)
            if not local or n(F(local,"UUID_Ressource"))!=n(resource_uuid):continue
        delete_ids.append(row["id"])
        log.append(f"PLANNING DEDUP | Ressource={local_id} | Date={date_key(F(row,'Date'))} | suppression ligne locale #{row['id']}")

    if delete_ids:
        try:
            unique_delete_ids=list(dict.fromkeys(delete_ids))
            for i in range(0,len(unique_delete_ids),500):
                delete_records(DEMANDES,"PLANNING_PRESENCE",unique_delete_ids[i:i+500])
            deleted=len(unique_delete_ids)
        except Exception as exc:
            errors+=1;log.append(f"ERREUR suppression des lignes planning obsolètes/doublons: {exc}")

    log.append(f"PLANNING {reason} | clé=Ressource+Date | période={a}->{b} | source={len(source_rows)} | clés_source={len(source_by_key)} | conflits_source={len(source_conflicts)} | créées={created} | maj={updated} | supprimées={deleted} | erreurs={errors}")
    return {"read":len(source_rows),"created":created,"updated":updated,"deleted":deleted,"warnings":warnings,"errors":errors,"source_conflicts":len(source_conflicts),"start":a,"end":b}

def load_sync_params(log):
    try: rows=rec(DEMANDES,"PARAM_SYNCHRO")
    except Exception as exc:
        log.append(f"AVERTISSEMENT PARAM_SYNCHRO non lisible: {exc}");return {}
    return {n(F(r,"Cle")):n(F(r,"Valeur")) for r in rows if n(F(r,"Cle"))}

def maybe_enqueue_weekly_full_sync(log):
    params=load_sync_params(log)
    if not bool_value(params.get("SYNC_HEBDO_ACTIF"),False):return {"enqueued":0,"reason":"disabled"}
    day_name=n(params.get("SYNC_HEBDO_JOUR") or "DIMANCHE").upper()
    weekday_map={"LUNDI":0,"MARDI":1,"MERCREDI":2,"JEUDI":3,"VENDREDI":4,"SAMEDI":5,"DIMANCHE":6}
    wanted=weekday_map.get(day_name,6)
    try:
        hh,mm=(params.get("SYNC_HEBDO_HEURE") or "22:00").split(":",1);hh=int(hh);mm=int(mm)
    except Exception:
        hh,mm=22,0
    current=datetime.now(LOG_TZ)
    if current.weekday()!=wanted or (current.hour,current.minute)<(hh,mm):return {"enqueued":0,"reason":"not_due"}
    iso=current.isocalendar();key=f"{iso.year}-W{iso.week:02d}"
    if STATE.get("last_weekly_sync_key")==key:return {"enqueued":0,"reason":"already_enqueued"}
    a,b=current_year_bounds()
    try:
        create(DEMANDES,"DEMANDES_SYNCHRO",{"Date_Debut":date_epoch(a),"Date_Fin":date_epoch(b),"Type_Synchro":"HEBDO_ANNUELLE","Statut":"EN_ATTENTE","Demandee_Par":"RH-SYNC","Date_Demande":now(),"Force_Full":True,"Message":"Déclenchement automatique hebdomadaire"})
        STATE["last_weekly_sync_key"]=key;save_state(STATE)
        log.append(f"SYNC HEBDO | demande créée pour {a}->{b} | semaine={key}")
        return {"enqueued":1,"reason":"due","week":key}
    except Exception as exc:
        log.append(f"ERREUR création demande hebdomadaire: {exc}")
        return {"enqueued":0,"reason":"error","errors":1}

def process_manual_sync_requests(log,max_requests=3):
    try: rows=rec(DEMANDES,"DEMANDES_SYNCHRO")
    except Exception as exc:
        log.append(f"AVERTISSEMENT DEMANDES_SYNCHRO non lisible: {exc}");return {"processed":0,"errors":0,"unavailable":1}
    pending=[r for r in rows if normalized_status(F(r,"Statut"))=="EN_ATTENTE"]
    pending.sort(key=lambda r:(F(r,"Date_Demande") or 0,r["id"]))
    processed=errors=0;created=updated=deleted=read=0
    for req in pending[:max_requests]:
        rid=req["id"];f=req.get("fields") or {}
        try:
            a,b=daterange_bounds(f.get("Date_Debut"),f.get("Date_Fin"))
            patch(DEMANDES,"DEMANDES_SYNCHRO",rid,{"Statut":"EN_COURS","Date_Debut_Execution":now(),"Message":"Synchronisation en cours"})
            result=sync_presence_period(log,a,b,force_full=bool_value(f.get("Force_Full")),reason=n(f.get("Type_Synchro")) or "MANUELLE")
            read+=result["read"];created+=result["created"];updated+=result["updated"];deleted+=result["deleted"];errors+=result["errors"]
            status="TERMINEE" if result["errors"]==0 else "ERREUR"
            msg=f"Planning synchronisé: {result['read']} lues, {result['created']} créées, {result['updated']} MAJ, {result['deleted']} supprimées"
            patch(DEMANDES,"DEMANDES_SYNCHRO",rid,{"Statut":status,"Date_Fin_Execution":now(),"Nb_Lignes_Lues":result["read"],"Nb_Lignes_Creees":result["created"],"Nb_Lignes_MAJ":result["updated"],"Nb_Erreurs":result["errors"],"Message":msg})
            processed+=1
        except Exception as exc:
            errors+=1
            try:patch(DEMANDES,"DEMANDES_SYNCHRO",rid,{"Statut":"ERREUR","Date_Fin_Execution":now(),"Nb_Erreurs":1,"Message":str(exc)[:1000]})
            except Exception:pass
            log.append(f"ERREUR demande synchro #{rid}: {exc}")
    return {"processed":processed,"read":read,"created":created,"updated":updated,"deleted":deleted,"errors":errors}

def backfill_request_teams(log):
    """Rattrapage idempotent des demandes sans équipe (aucun écrasement)."""
    requests=rec(COCKPIT,"Demandes_RH")
    teams={r["id"]:r for r in rec(COCKPIT,"Team")}
    team_index=team_ref_index(rec(COCKPIT,"Team_ref"))
    updated=skipped=warnings=errors=0
    log.append(f"RATTRAPAGE | démarrage | demandes_cockpit={len(requests)} | lignes_Team={len(teams)} | lignes_Team_ref={len(team_index[0])} | libellés_uniques={len(team_index[1])} | libellés_ambigus={len(team_index[2])}")
    for request in requests:
        fields=request.get("fields") or {}
        if n(fields.get("Equipe")):
            skipped+=1
            log.append(f"RATTRAPAGE demande #{request['id']} | action=IGNORE | Equipe existante={short_value(fields.get('Equipe'))}")
            continue
        person_id=refid(fields.get("Demandeur"))
        person=teams.get(person_id)
        if not person:
            warnings+=1
            log.append(f"AVERTISSEMENT demande #{request['id']}: Demandeur non résolu dans Team | valeur_brute={short_value(fields.get('Demandeur'))} | id_interprété={person_id}")
            continue
        team_id,reason=resolve_team_id(team_equipo_value(person),team_index)
        if not team_id:
            warnings+=1
            log.append(f"AVERTISSEMENT demande #{request['id']}: Team #{person_id} : {reason}.")
            describe_request_team(log,request['id'],person,team_index,reason)
            continue
        try:
            patch(COCKPIT,"Demandes_RH",request["id"],{"Equipe":team_id})
            updated+=1
            log.append(f"RATTRAPAGE demande #{request['id']} | action=CORRIGEE | demandeur=Team #{person_id} | Team.equipe={short_value(F(person,'Equipe'))} | Team_ref.id={team_id}")
        except Exception as exc:
            errors+=1
            log.append(f"ERREUR demande #{request['id']}: écriture Equipe impossible : {exc}")
    log.append(f"RATTRAPAGE | fin | corrigées={updated} | déjà_renseignées={skipped} | anomalies={warnings} | erreurs={errors}")
    return {"updated":updated,"already_set":skipped,"warnings":warnings,"errors":errors}


def sync_decisions(log):
    src,dst=rec(COCKPIT,"Demandes_RH"),rec(DEMANDES,"Demandes_RH")
    try: lres=rec(DEMANDES,"Ressources")
    except Exception: lres=[]
    lres_by_id={r["id"]:r for r in lres}
    try: teams=rec(COCKPIT,"Team")
    except Exception: teams=[]
    teams_by_id={r["id"]:r for r in teams}
    di,ddup=idx(dst,"UUID_Demande");u=e=mail_count=planning_runs=0
    auto_params=load_sync_params(log)
    auto_presence=bool_value(auto_params.get("SYNC_AUTO_VALIDATION_ACTIF"),True)
    for r in src:
        f=r["fields"];uid=n(f.get("UUID_Demande"))
        if not uid or uid not in di:continue
        if uid in ddup:e+=1;log.append(f"UUID dupliqué portail: {uid}");continue
        local=di[uid]
        manager_email=n(f.get("Manager_Email"))
        if not manager_email:
            mgr=teams_by_id.get(refid(f.get("Manager")))
            if mgr: manager_email=n(F(mgr,"email") or F(mgr,"Email"))
        new_status=n(f.get("Statut") or "EN_ATTENTE").upper()
        decision_payload={"Statut":new_status,"Manager":refid(f.get("Manager")) or "",
          "Manager_Email":manager_email,"Commentaire_Manager":f.get("Commentaire_Manager") or "",
          "Date_Decision":f.get("Date_Decision")}
        fp=fingerprint(decision_payload)
        previous=STATE.setdefault("cockpit",{}).get(uid)
        changed=(previous is not None and previous!=fp)
        first_seen=(previous is None)
        needs_write=changed or first_seen
        fields={"Statut":new_status,"Manager_Email":manager_email,
          "Commentaire_Manager":f.get("Commentaire_Manager") or "","Date_Decision":f.get("Date_Decision"),
          "Date_Modification":now()}
        try:
            if needs_write:
                patch(DEMANDES,"Demandes_RH",local["id"],fields);u+=1
                STATE["cockpit"][uid]=fp; save_state(STATE)

                # Une validation nouvelle déclenche immédiatement la relecture de Cockpit.Presences
                # sur la période de la demande, pour cette ressource uniquement.
                if changed and auto_presence and is_validated_status(new_status):
                    local_person=lres_by_id.get(refid(F(local,"Demandeur")) or F(local,"Demandeur"),{})
                    resource_uuid=n(F(local_person,"UUID_Ressource"))
                    a=F(local,"Date_Debut");b=F(local,"Date_Fin")
                    if not resource_uuid:
                        e+=1;log.append(f"ERREUR planning après validation {uid}: UUID_Ressource local absent; synchronisation ciblée non lancée")
                    else:
                        try:
                            result=sync_presence_period(log,a,b,resource_uuid=resource_uuid,force_full=True,reason=f"VALIDATION {uid}")
                            planning_runs+=1;e+=result.get("errors",0)
                            if result.get("read",0)==0:
                                log.append(f"AVERTISSEMENT validation {uid}: aucune ligne Cockpit.Presences trouvée sur la période; une synchro manuelle/hebdo ultérieure pourra rattraper le planning")
                        except Exception as px:
                            e+=1;log.append(f"ERREUR planning après validation {uid}: {px}")

            notify=changed or (first_seen and NOTIFY_EXISTING_ON_FIRST_RUN)
            if notify and needs_write:
                demandeur=lres_by_id.get(refid(F(local,"Demandeur")) or F(local,"Demandeur"),{})
                email=requester_email(demandeur)
                ref=n(F(local,"Reference")) or uid
                portal_link=f"\nPortail : {PORTAL_URL}\n" if PORTAL_URL else ""
                commentaire=n(f.get("Commentaire_Manager"))
                if email:
                    body=(f"Votre demande RH a été mise à jour par votre manager et synchronisée.\n\n"
                          f"Référence : {ref}\nStatut : {new_status}\n"
                          +(f"Commentaire manager : {commentaire}\n" if commentaire else "")+portal_link)
                    if send_mail(email,f"[RH] Mise à jour demande {ref} — {new_status}",body,log): mail_count+=1
                elif SMTP_ENABLED: log.append(f"EMAIL {uid}: email demandeur absent.")

                if manager_email:
                    cockpit_link=f"\nCockpit : {COCKPIT_URL}\n" if COCKPIT_URL else ""
                    body=(f"Votre modification de la demande RH a bien été synchronisée vers le portail collaborateur.\n\n"
                          f"Référence : {ref}\nStatut : {new_status}\n"
                          +(f"Commentaire : {commentaire}\n" if commentaire else "")+cockpit_link)
                    if send_mail(manager_email,f"[RH] Modification synchronisée {ref}",body,log): mail_count+=1
                elif SMTP_ENABLED: log.append(f"EMAIL {uid}: email manager absent, confirmation non envoyée.")
        except Exception as x:e+=1;log.append(f"Retour {uid}: {x}")
    return {"updated":u,"emails":mail_count,"planning_after_validation":planning_runs,"errors":e}

def journal(status,summary,details):
    try:create(DEMANDES,"Journal_Sync",{"Run_ID":str(uuid.uuid4()),"Date_Sync":now(),"Statut":status,
      "Resume":json.dumps(summary,ensure_ascii=False),"Details":"\n".join(details)[-12000:]})
    except Exception as e:print("WARN Journal_Sync:",e,file=sys.stderr)

details=TimestampedLog();summary={}
cycle_started=timestamp()
details.append("Début du cycle RH-SYNC V3.10")
try:
    if SMTP_ENABLED:
        details.append(f"INFO SMTP activé: {SMTP_HOST}:{SMTP_PORT} sécurité={SMTP_SECURITY} expéditeur={SMTP_FROM}")
    details.append("ETAPE 1/7 | synchronisation des ressources + équipes : démarrage")
    summary["ressources"]=sync_resources(details)
    details.append(f"ETAPE 1/7 | ressources : {json.dumps(summary['ressources'],ensure_ascii=False)}")
    details.append("ETAPE 2/7 | demandes vers Cockpit : démarrage")
    summary["demandes_vers_cockpit"]=sync_requests(details)
    details.append(f"ETAPE 2/7 | demandes : {json.dumps(summary['demandes_vers_cockpit'],ensure_ascii=False)}")
    details.append("ETAPE 3/7 | rattrapage des équipes : démarrage")
    summary["rattrapage_equipes"]=backfill_request_teams(details)
    details.append(f"ETAPE 3/7 | rattrapage : {json.dumps(summary['rattrapage_equipes'],ensure_ascii=False)}")
    details.append("ETAPE 4/7 | décisions vers Portail + planning après validation : démarrage")
    summary["decisions_vers_portail"]=sync_decisions(details)
    details.append(f"ETAPE 4/7 | décisions : {json.dumps(summary['decisions_vers_portail'],ensure_ascii=False)}")
    details.append("ETAPE 5/7 | déclenchement hebdomadaire éventuel : démarrage")
    summary["hebdomadaire"]=maybe_enqueue_weekly_full_sync(details)
    details.append(f"ETAPE 5/7 | hebdomadaire : {json.dumps(summary['hebdomadaire'],ensure_ascii=False)}")
    details.append("ETAPE 6/7 | demandes de synchronisation manuelle/hebdomadaire : démarrage")
    summary["planning_requests"]=process_manual_sync_requests(details)
    details.append(f"ETAPE 6/7 | planning : {json.dumps(summary['planning_requests'],ensure_ascii=False)}")
    details.append("ETAPE 7/7 | finalisation du cycle")
    errors=sum(x.get("errors",0) for x in summary.values() if isinstance(x,dict))
    status="OK" if errors==0 else "AVEC_ERREURS"
    details.append(f"Fin du cycle RH-SYNC : {status} ; bilan={json.dumps(summary,ensure_ascii=False)}")
    cycle_finished=timestamp()
    journal(status,summary,details)
    print(json.dumps({"timestamp":cycle_finished,"started_at":cycle_started,"status":status,"summary":summary,"details":details},ensure_ascii=False,indent=2),flush=True)
    sys.exit(0 if errors==0 else 2)
except Exception as e:
    details.append(str(e));details.append(traceback.format_exc());journal("ECHEC",summary,details)
    print(json.dumps({"timestamp":timestamp(),"started_at":cycle_started,"status":"ECHEC","error":str(e),"details":details},ensure_ascii=False,indent=2),flush=True);sys.exit(1)
